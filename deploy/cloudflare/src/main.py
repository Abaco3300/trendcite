"""Non-production Cloudflare Python Worker scaffold for TrendCite Pro v1.

This file is intentionally deployment-inert until concrete non-production resource
bindings and a scheduler adapter are authorized in a later gate.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from http_transport import CloudflareFetchTransport, CloudflarePostTransport
from workers import Response, WorkerEntrypoint

from trendcite.cloud.async_application import AsyncCloudApplicationRunner
from trendcite.cloud.async_delivery import PostmarkConfig, PostmarkDeliveryAdapter
from trendcite.cloud.async_delivery_service import AsyncDeliveryService
from trendcite.cloud.async_execution import AsyncExecutionPipelineImpl
from trendcite.cloud.async_scheduler import AsyncScheduledCoordinator
from trendcite.cloud.async_sources import AsyncSourceExecutionServiceImpl
from trendcite.cloud.db.postgres import AsyncpgHyperdriveConnector, PostgresRuntimeStore
from trendcite.cloud.db.postgres_delivery import PostgresDeliveryStore
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
    return AsyncCloudApplicationRunner(execution_store, pipeline)


def _coordinator(env: Any) -> AsyncScheduledCoordinator:
    if not hasattr(env, "TREND_QUEUE"):
        raise RuntimeError("TREND_QUEUE binding is required")
    return AsyncScheduledCoordinator(
        _store(env),
        _CloudflareQueuePublisher(env.TREND_QUEUE),
        _runner(env),
        worker_id="cloudflare-scheduler",
    )


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
        if str(request.url).endswith("/health"):
            ok = await _store(self.env).healthcheck()
            return Response.json({"ok": ok})
        return Response.json({"ok": False, "error": "not_found"}, status=404)

    async def queue(self, batch: Any, env: Any = None, ctx: Any = None) -> None:
        runtime_env = env if env is not None else self.env
        store = _store(runtime_env)
        for message in batch.messages:
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
                print(
                    json.dumps(
                        {
                            "event": "trendcite.queue.delivery",
                            "status": "retry",
                            "error_type": type(exc).__name__,
                        },
                        sort_keys=True,
                    )
                )
                message.retry()

    async def scheduled(self, controller: Any, env: Any, ctx: Any) -> None:
        runtime_env = env if env is not None else self.env
        result = await _coordinator(runtime_env).plan_and_enqueue(
            now=datetime.now(UTC).replace(microsecond=0)
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
                },
                sort_keys=True,
            )
        )
