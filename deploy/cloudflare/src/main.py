"""Non-production Cloudflare Python Worker scaffold for TrendCite Pro v1.

This file is intentionally deployment-inert until concrete non-production resource
bindings and a scheduler adapter are authorized in a later gate.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from workers import Response, WorkerEntrypoint

from trendcite.cloud.async_scheduler import AsyncRunResult, AsyncScheduledCoordinator
from trendcite.cloud.db.postgres import AsyncpgHyperdriveConnector, PostgresRuntimeStore


class _CloudflareQueuePublisher:
    def __init__(self, binding: Any) -> None:
        self.binding = binding

    async def send(self, payload: dict[str, str]) -> None:
        await self.binding.send(json.dumps(payload, separators=(",", ":")))


class _UnwiredRadarRunner:
    async def run_radar(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
    ) -> AsyncRunResult:
        raise RuntimeError("async radar runner is not configured")


def _store(env: Any) -> PostgresRuntimeStore:
    if not hasattr(env, "HYPERDRIVE"):
        raise RuntimeError("HYPERDRIVE binding is required")
    return PostgresRuntimeStore(AsyncpgHyperdriveConnector(env.HYPERDRIVE))


def _coordinator(env: Any) -> AsyncScheduledCoordinator:
    if not hasattr(env, "TREND_QUEUE"):
        raise RuntimeError("TREND_QUEUE binding is required")
    return AsyncScheduledCoordinator(
        _store(env),
        _CloudflareQueuePublisher(env.TREND_QUEUE),
        _UnwiredRadarRunner(),
        worker_id="cloudflare-scheduler",
    )


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
                if kind == "scheduled_radar_tick":
                    # Scheduled ticks are NOT deduped by cloud_queue_delivery. The
                    # atomic cloud_schedule_tick claim + lease is the authority: a
                    # transport retry must remain available if a claimant crashes.
                    print(
                        json.dumps(
                            {
                                "event": "trendcite.queue.scheduled_tick",
                                "status": "scheduler_not_wired",
                                "tick_id": str(payload.get("tick_id") or ""),
                            },
                            sort_keys=True,
                        )
                    )
                    message.retry()
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
        result = await _coordinator(env).plan_and_enqueue(
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
                    "execution_runner": "not_configured",
                },
                sort_keys=True,
            )
        )
