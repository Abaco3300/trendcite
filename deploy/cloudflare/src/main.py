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

from trendcite.cloud.db.postgres import AsyncpgHyperdriveConnector, PostgresRuntimeStore


def _store(env: Any) -> PostgresRuntimeStore:
    if not hasattr(env, "HYPERDRIVE"):
        raise RuntimeError("HYPERDRIVE binding is required")
    return PostgresRuntimeStore(AsyncpgHyperdriveConnector(env.HYPERDRIVE))


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
                inserted = await store.record_queue_once(
                    delivery_id=str(payload.get("delivery_id") or uuid.uuid4().hex),
                    workspace_id=str(payload["workspace_id"]),
                    logical_id=str(payload["logical_id"]),
                    kind=str(payload["kind"]),
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
        # Architecture scaffold only. Persistence connectivity is validated here;
        # planning/claim/execution wiring is intentionally a later local build block.
        ok = await _store(env).healthcheck()
        print(
            json.dumps(
                {
                    "event": "trendcite.scheduler.tick",
                    "persistence_ready": ok,
                    "cron": str(getattr(controller, "cron", "")),
                    "scheduled_time": str(getattr(controller, "scheduledTime", "")),
                    "scheduler_adapter": "not_configured",
                },
                sort_keys=True,
            )
        )

[executed on device: LAPTOP-JOSEMILE (056f59c1-dbac-4f47-875e-044865a705aa)]