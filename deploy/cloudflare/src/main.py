"""Non-production Cloudflare Python Worker for TrendCite Pro v1.

HTTP surface: /health and the authenticated customer API under /api/v1 (see
trendcite.cloud.customer_api). Everything else is served by Workers static assets
(the customer frontend) when an assets directory is configured.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from http_transport import CloudflareFetchTransport, CloudflarePostTransport
from workers import Response, WorkerEntrypoint

from trendcite.cloud.async_application import AsyncCloudApplicationRunner
from trendcite.cloud.async_automation import AsyncAutomationReconciler
from trendcite.cloud.async_delivery import PostmarkConfig, PostmarkDeliveryAdapter
from trendcite.cloud.async_delivery_service import AsyncDeliveryService
from trendcite.cloud.async_execution import AsyncExecutionPipelineImpl
from trendcite.cloud.async_scheduler import AsyncScheduledCoordinator
from trendcite.cloud.async_sources import AsyncSourceExecutionServiceImpl
from trendcite.cloud.auth import AsyncSupabaseAuth, SupabaseAuthConfig
from trendcite.cloud.customer_api import (
    ApiRequest,
    CustomerApi,
    is_customer_api_path,
    mutations_enabled,
)
from trendcite.cloud.db.postgres import AsyncpgHyperdriveConnector, PostgresRuntimeStore
from trendcite.cloud.db.postgres_automation import PostgresAutomationStore
from trendcite.cloud.db.postgres_customer import PostgresCustomerStore
from trendcite.cloud.db.postgres_delivery import PostgresDeliveryStore
from trendcite.cloud.db.postgres_entitlements import PostgresEntitlementStore
from trendcite.cloud.db.postgres_execution import PostgresExecutionStore
from trendcite.cloud.domain.alerts import DELIVERY_PENDING
from trendcite.config import Config


class _CloudflareQueuePublisher:
    def __init__(self, binding: Any) -> None:
        self.binding = binding

    async def send(self, payload: dict[str, str]) -> None:
        await self.binding.send(json.dumps(payload, separators=(",", ":")))


def _connector(env: Any) -> AsyncpgHyperdriveConnector:
    if not hasattr(env, "HYPERDRIVE"):
        raise RuntimeError("HYPERDRIVE binding is required")
    return AsyncpgHyperdriveConnector(env.HYPERDRIVE)


def _runtime_role(env: Any) -> str:
    role = str(getattr(env, "TRENDCITE_RUNTIME_ROLE", "trendcite_runtime"))
    if not role:
        raise RuntimeError("TRENDCITE_RUNTIME_ROLE must not be empty")
    return role


def _store(env: Any) -> PostgresRuntimeStore:
    return PostgresRuntimeStore(_connector(env), runtime_role=_runtime_role(env))


def _entitlements_enabled(env: Any) -> bool:
    flag = str(getattr(env, "TRENDCITE_ENTITLEMENTS", "") or "").strip()
    return flag == "nonprod-enabled" and "nonprod" in _runtime_role(env)


def _entitlement_store(env: Any) -> PostgresEntitlementStore:
    return PostgresEntitlementStore(
        _connector(env),
        runtime_role=_runtime_role(env),
    )


def _automation_store(env: Any) -> PostgresAutomationStore:
    return PostgresAutomationStore(
        _connector(env),
        runtime_role=_runtime_role(env),
    )


def _automation_enabled(env: Any) -> bool:
    flag = str(getattr(env, "TRENDCITE_AUTOMATION", "") or "").strip()
    return flag == "nonprod-enabled" and "nonprod" in _runtime_role(env)


def _env_positive_int(env: Any, name: str, default: int) -> int:
    raw = str(getattr(env, name, "") or "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 1:
        raise RuntimeError(f"{name} must be positive")
    return value


def _env_datetime(env: Any, name: str) -> datetime:
    raw = str(getattr(env, name, "") or "").strip()
    if not raw:
        raise RuntimeError(f"{name} is required")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _automation_reconciler(env: Any) -> AsyncAutomationReconciler:
    return AsyncAutomationReconciler(
        _automation_store(env),
        _CloudflareQueuePublisher(env.TREND_QUEUE),
        stale_seconds=_env_positive_int(env, "TRENDCITE_AUTOMATION_STALE_SECONDS", 120),
        recovery_after=_env_datetime(env, "TRENDCITE_AUTOMATION_RECOVERY_AFTER"),
    )


def _runner(env: Any) -> AsyncCloudApplicationRunner:
    execution_store = PostgresExecutionStore(
        _connector(env),
        runtime_role=_runtime_role(env),
    )
    source_service = AsyncSourceExecutionServiceImpl(
        CloudflareFetchTransport(),
        config=Config(),
    )
    pipeline = AsyncExecutionPipelineImpl(execution_store, source_service)
    gate = _entitlement_store(env) if _entitlements_enabled(env) else None
    return AsyncCloudApplicationRunner(execution_store, pipeline, gate)


def _coordinator(env: Any) -> AsyncScheduledCoordinator:
    if not hasattr(env, "TREND_QUEUE"):
        raise RuntimeError("TREND_QUEUE binding is required")
    return AsyncScheduledCoordinator(
        _store(env),
        _CloudflareQueuePublisher(env.TREND_QUEUE),
        _runner(env),
        worker_id="cloudflare-scheduler",
    )


def _auth_service(env: Any) -> AsyncSupabaseAuth:
    supabase_url = str(getattr(env, "SUPABASE_URL", "")).strip()
    publishable_key = str(getattr(env, "SUPABASE_PUBLISHABLE_KEY", "")).strip()
    if not supabase_url or not publishable_key:
        raise RuntimeError("Supabase Auth bindings are required")
    return AsyncSupabaseAuth(
        CloudflareFetchTransport(),
        SupabaseAuthConfig(
            supabase_url=supabase_url,
            publishable_key=publishable_key,
        ),
    )


def _customer_store(env: Any) -> PostgresCustomerStore:
    return PostgresCustomerStore(
        _connector(env),
        runtime_role=_runtime_role(env),
    )


def _log_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, sort_keys=True))


async def _customer_api_response(env: Any, request: Any) -> Any:
    """Adapt a Fetch request to the transport-neutral customer API.

    The Authorization header is handed to the auth service and never logged; the
    body is read only for methods that can carry one.
    """

    method = str(request.method).upper()
    body = b""
    if method in {"POST", "PUT", "PATCH"}:
        body = str(await request.text()).encode("utf-8")
    parsed = urlparse(request.url)
    try:
        api = CustomerApi(
            _auth_service(env),
            _customer_store(env),
            mutations_enabled=mutations_enabled(env),
            entitlement_store=_entitlement_store(env),
            automation_store=_automation_store(env),
            automation_stale_seconds=_env_positive_int(
                env, "TRENDCITE_AUTOMATION_STALE_SECONDS", 120
            ),
            scheduler_stale_seconds=_env_positive_int(
                env, "TRENDCITE_SCHEDULER_STALE_SECONDS", 600
            ),
            log=_log_event,
        )
    except RuntimeError as exc:
        _log_event(
            {"event": "trendcite.customer_api.misconfigured", "error_type": type(exc).__name__}
        )
        return Response.json({"ok": False, "error": "unavailable"}, status=503)
    result = await api.handle(
        ApiRequest(
            method=method,
            path=parsed.path,
            query=parsed.query,
            authorization=request.headers.get("Authorization"),
            content_type=str(request.headers.get("Content-Type") or ""),
            body=body,
        )
    )
    return Response.json(result.payload, status=result.status, headers=dict(result.headers))


def _delivery_service(env: Any) -> AsyncDeliveryService | None:
    provider = str(getattr(env, "TRENDCITE_DELIVERY_PROVIDER", "")).strip()
    if not provider:
        return None
    if provider != "postmark-nonprod":
        raise RuntimeError("unsupported or production delivery provider")

    required = (
        "POSTMARK_SERVER_TOKEN",
        "POSTMARK_FROM",
        "TRENDCITE_NONPROD_DELIVERY_TO",
    )
    missing = [name for name in required if not str(getattr(env, name, "")).strip()]
    if missing:
        raise RuntimeError("missing delivery bindings: " + ", ".join(missing))

    recipient = str(env.TRENDCITE_NONPROD_DELIVERY_TO).strip()
    config = PostmarkConfig(
        server_token=str(env.POSTMARK_SERVER_TOKEN),
        sender=str(env.POSTMARK_FROM),
        recipient_for_workspace=lambda _workspace_id: recipient,
    )
    store = PostgresDeliveryStore(
        _connector(env),
        runtime_role=_runtime_role(env),
    )
    port = PostmarkDeliveryAdapter(CloudflarePostTransport(), config)
    return AsyncDeliveryService(store, port)


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        path = urlparse(request.url).path
        if path == "/health":
            ok = await _store(self.env).healthcheck()
            return Response.json({"ok": ok})

        if is_customer_api_path(path):
            return await _customer_api_response(self.env, request)

        if hasattr(self.env, "ASSETS"):
            return await self.env.ASSETS.fetch(request)

        return Response.json({"ok": False, "error": "not_found"}, status=404)

    async def queue(self, batch: Any, env: Any = None, ctx: Any = None) -> None:
        runtime_env = env if env is not None else self.env
        store = _store(runtime_env)
        for message in batch.messages:
            payload: dict[str, Any] = {}
            try:
                payload = json.loads(str(message.body))
                required = ("workspace_id", "logical_id", "kind")
                missing = [name for name in required if not payload.get(name)]
                if missing:
                    raise ValueError("missing queue fields: " + ", ".join(missing))
                kind = str(payload["kind"])
                if kind == "deliver_alert":
                    delivery = _delivery_service(runtime_env)
                    if delivery is None:
                        raise RuntimeError("delivery provider is not configured")
                    alert_id = str(payload.get("alert_id") or "")
                    if not alert_id:
                        raise ValueError("deliver_alert requires alert_id")
                    alert = await delivery.deliver_alert(
                        str(payload["workspace_id"]),
                        alert_id,
                    )
                    print(
                        json.dumps(
                            {
                                "event": "trendcite.queue.deliver_alert",
                                "alert_id": alert.alert_id,
                                "delivery_state": alert.delivery_state,
                                "attempt_count": alert.attempt_count,
                            },
                            sort_keys=True,
                        )
                    )
                    if alert.delivery_state == DELIVERY_PENDING:
                        message.retry()
                    else:
                        message.ack()
                    continue

                if kind == "build_digest":
                    delivery = _delivery_service(runtime_env)
                    if delivery is None:
                        raise RuntimeError("delivery provider is not configured")
                    radar_id = str(payload.get("radar_id") or "")
                    radar_name = str(payload.get("radar_name") or radar_id)
                    day_text = str(payload.get("day") or "")
                    if not radar_id or not day_text:
                        raise ValueError("build_digest requires radar_id and day")
                    digest = await delivery.build_digest(
                        workspace_id=str(payload["workspace_id"]),
                        radar_id=radar_id,
                        radar_name=radar_name,
                        day=datetime.fromisoformat(day_text),
                    )
                    if digest is not None:
                        await _CloudflareQueuePublisher(runtime_env.TREND_QUEUE).send(
                            {
                                "workspace_id": digest.workspace_id,
                                "logical_id": f"digest:{digest.digest_id}",
                                "kind": "deliver_digest",
                                "digest_id": digest.digest_id,
                            }
                        )
                    message.ack()
                    continue

                if kind == "deliver_digest":
                    delivery = _delivery_service(runtime_env)
                    if delivery is None:
                        raise RuntimeError("delivery provider is not configured")
                    digest_id = str(payload.get("digest_id") or "")
                    if not digest_id:
                        raise ValueError("deliver_digest requires digest_id")
                    digest = await delivery.deliver_digest(
                        str(payload["workspace_id"]),
                        digest_id,
                    )
                    print(
                        json.dumps(
                            {
                                "event": "trendcite.queue.deliver_digest",
                                "digest_id": digest.digest_id,
                                "delivery_state": digest.delivery_state,
                                "attempt_count": digest.attempt_count,
                            },
                            sort_keys=True,
                        )
                    )
                    if digest.delivery_state == DELIVERY_PENDING:
                        message.retry()
                    else:
                        message.ack()
                    continue

                if kind == "scheduled_radar_tick":
                    outcome = await _coordinator(runtime_env).execute_message(
                        payload,
                        now=datetime.now(UTC).replace(microsecond=0),
                    )
                    delivery_enqueued = 0
                    if outcome.status == "succeeded" and outcome.run_id:
                        delivery = _delivery_service(runtime_env)
                        if delivery is not None:
                            alerts = await delivery.materialize_run_alerts(
                                str(payload["workspace_id"]),
                                outcome.run_id,
                            )
                            publisher = _CloudflareQueuePublisher(runtime_env.TREND_QUEUE)
                            for alert in alerts:
                                await publisher.send(
                                    {
                                        "workspace_id": alert.workspace_id,
                                        "logical_id": f"alert:{alert.alert_id}",
                                        "kind": "deliver_alert",
                                        "alert_id": alert.alert_id,
                                    }
                                )
                            delivery_enqueued = len(alerts)

                    print(
                        json.dumps(
                            {
                                "event": "trendcite.queue.scheduled_tick",
                                "tick_id": outcome.tick_id,
                                "status": outcome.status,
                                "claimed": outcome.claimed,
                                "settled": outcome.settled,
                                "requeued": outcome.requeued,
                                "retry_transport": outcome.retry_transport,
                                "delivery_enqueued": delivery_enqueued,
                            },
                            sort_keys=True,
                        )
                    )
                    if outcome.retry_transport:
                        message.retry()
                    else:
                        message.ack()
                    continue

                inserted = await store.record_queue_once(
                    delivery_id=str(payload.get("delivery_id") or uuid.uuid4().hex),
                    workspace_id=str(payload["workspace_id"]),
                    logical_id=str(payload["logical_id"]),
                    kind=kind,
                    first_seen_at=datetime.now(UTC).replace(microsecond=0),
                )
                print(
                    json.dumps(
                        {
                            "event": "trendcite.queue.delivery",
                            "logical_id": str(payload["logical_id"]),
                            "inserted": inserted,
                            "duplicate": not inserted,
                        },
                        sort_keys=True,
                    )
                )
                message.ack()
            except Exception as exc:
                if payload.get("workspace_id") and payload.get("logical_id"):
                    try:
                        await _automation_store(runtime_env).record_queue_failure(
                            workspace_id=str(payload["workspace_id"]),
                            logical_id=str(payload["logical_id"]),
                            kind=str(payload.get("kind") or "unknown"),
                            queue_message_id=str(getattr(message, "id", "") or ""),
                            attempt=int(getattr(message, "attempts", 1) or 1),
                            max_attempts=_env_positive_int(
                                runtime_env, "TRENDCITE_QUEUE_MAX_ATTEMPTS", 3
                            ),
                            error_type=type(exc).__name__,
                            observed_at=datetime.now(UTC).replace(microsecond=0),
                        )
                    except Exception as audit_exc:
                        print(
                            json.dumps(
                                {
                                    "event": "trendcite.queue.failure_audit_error",
                                    "error_type": type(audit_exc).__name__,
                                },
                                sort_keys=True,
                            )
                        )
                print(
                    json.dumps(
                        {
                            "event": "trendcite.queue.delivery",
                            "status": "retry",
                            "error_type": type(exc).__name__,
                            "attempt": int(getattr(message, "attempts", 1) or 1),
                        },
                        sort_keys=True,
                    )
                )
                message.retry()

    async def scheduled(self, controller: Any, env: Any, ctx: Any) -> None:
        runtime_env = env if env is not None else self.env
        now = datetime.now(UTC).replace(microsecond=0)
        result = await _coordinator(runtime_env).plan_and_enqueue(now=now)

        recovery_candidates = 0
        recovery_requeued = 0
        recovery_terminalized = 0
        recovery_already_recorded = 0
        if _automation_enabled(runtime_env):
            recovery = await _automation_reconciler(runtime_env).reconcile(now=now)
            recovery_candidates = recovery.candidates
            recovery_requeued = recovery.requeued
            recovery_terminalized = recovery.terminalized
            recovery_already_recorded = recovery.already_recorded

        heartbeat_detail = {
            "cron": str(getattr(controller, "cron", "")),
            "schedules": len(result.schedules),
            "enqueued": result.enqueued,
            "automation_enabled": _automation_enabled(runtime_env),
            "recovery_candidates": recovery_candidates,
            "recovery_requeued": recovery_requeued,
            "recovery_terminalized": recovery_terminalized,
            "recovery_already_recorded": recovery_already_recorded,
        }
        await _automation_store(runtime_env).record_heartbeat(
            "scheduler",
            observed_at=now,
            detail=heartbeat_detail,
        )
        print(
            json.dumps(
                {
                    "event": "trendcite.scheduler.tick",
                    "cron": str(getattr(controller, "cron", "")),
                    "scheduled_time": str(getattr(controller, "scheduledTime", "")),
                    "schedules": len(result.schedules),
                    "enqueued": result.enqueued,
                    "execution_runner": "async_sources_configured",
                    "automation_enabled": _automation_enabled(runtime_env),
                    "recovery_candidates": recovery_candidates,
                    "recovery_requeued": recovery_requeued,
                    "recovery_terminalized": recovery_terminalized,
                    "recovery_already_recorded": recovery_already_recorded,
                },
                sort_keys=True,
            )
        )
