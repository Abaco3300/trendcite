from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from trendcite.cloud.async_runtime import AsyncCloudRuntime
from trendcite.cloud.db.postgres import (
    HyperdriveConnectInfo,
    PostgresRuntimeStore,
    postgres_migration_batches,
)
from trendcite.cloud.domain.radar import RUN_COVERAGE_COMPLETE, RadarRun
from trendcite.cloud.domain.scheduling import CADENCE_HOURLY, RadarSchedule, plan_due


def _run(coro: Any) -> Any:
    """Drive a fake-only coroutine without constructing an OS event loop."""

    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake coroutine unexpectedly suspended")


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        return None


class _Conn:
    def __init__(self, *, rows: list[Any] | None = None, scalar: Any = 1) -> None:
        self.rows = list(rows or [])
        self.scalar = scalar
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> _Tx:
        return _Tx()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.calls.append((query, args))
        return list(self.rows)

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return self.scalar

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return self.rows.pop(0) if self.rows else None

    async def close(self) -> None:
        self.closed = True


class _Connector:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __call__(self) -> _Conn:
        return self.conn


def test_hyperdrive_binding_validation() -> None:
    class Binding:
        host = "hyperdrive.local"
        port = 5432
        user = "trendcite_login"
        password = "secret"
        database = "postgres"

    info = HyperdriveConnectInfo.from_binding(Binding())
    assert info.host == "hyperdrive.local"
    assert info.port == 5432

    class Missing:
        host = "x"

    with pytest.raises(RuntimeError, match="invalid Hyperdrive binding"):
        HyperdriveConnectInfo.from_binding(Missing())


def test_runtime_role_rejects_sql_identifier_injection() -> None:
    with pytest.raises(ValueError, match="PostgreSQL identifier"):
        PostgresRuntimeStore(_Connector(_Conn()), runtime_role="role; DROP SCHEMA public")


def test_healthcheck_closes_connection() -> None:
    conn = _Conn(scalar=1)
    store = PostgresRuntimeStore(_Connector(conn))
    assert _run(store.healthcheck()) is True
    assert conn.closed is True


def test_queue_dedupe_is_database_enforced_and_schema_qualified() -> None:
    conn = _Conn(rows=[{"delivery_id": "d1"}])
    store = PostgresRuntimeStore(_Connector(conn))
    inserted = _run(
        store.record_queue_once(
            delivery_id="d1",
            workspace_id="w1",
            logical_id="logical-1",
            kind="radar_run",
            first_seen_at=datetime(2026, 9, 28, tzinfo=UTC),
        )
    )
    assert inserted is True
    queries = "\n".join(query for query, _ in conn.calls)
    assert "SET LOCAL ROLE trendcite_runtime" in queries
    assert "INSERT INTO trendcite.cloud_queue_delivery" in queries
    assert "ON CONFLICT (workspace_id, logical_id) DO NOTHING" in queries
    assert conn.closed is True


def test_claim_tick_is_one_conditional_update() -> None:
    conn = _Conn(rows=[{"tick_id": "t1"}])
    store = PostgresRuntimeStore(_Connector(conn))
    now = datetime(2026, 9, 28, tzinfo=UTC)
    won = _run(
        store.claim_tick(
            workspace_id="w1",
            tick_id="t1",
            owner="worker-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=120),
        )
    )
    assert won is True
    update = next(
        query for query, _ in conn.calls if "UPDATE trendcite.cloud_schedule_tick" in query
    )
    assert "status='pending'" in update
    assert "status='failed' AND attempt<max_attempts" in update
    assert "status='running'" in update
    assert "RETURNING tick_id" in update


def test_portable_migrations_are_wrapped_in_trendcite_search_path() -> None:
    batches = postgres_migration_batches(["CREATE TABLE example (id TEXT PRIMARY KEY);"])
    assert len(batches) == 1
    assert batches[0].startswith("CREATE SCHEMA IF NOT EXISTS trendcite;")
    assert "SET search_path TO trendcite, pg_catalog;" in batches[0]


def test_postgres_adapter_contains_no_sync_over_async_bridge() -> None:
    source = Path("src/trendcite/cloud/db/postgres.py").read_text(encoding="utf-8")
    assert "run_until_complete" not in source
    assert "asyncio.run(" not in source


def test_async_runtime_dispatches_without_transport_coupling() -> None:
    class Scheduled:
        async def run_once(self, *, scheduled_time: str, cron: str) -> dict[str, Any]:
            return {"scheduled_time": scheduled_time, "cron": cron}

    class Queue:
        async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
            return {"logical_id": payload["logical_id"]}

    runtime = AsyncCloudRuntime(Scheduled(), Queue())
    scheduled = _run(runtime.scheduled(scheduled_time="100", cron="*/5 * * * *"))
    queued = _run(runtime.queue({"logical_id": "abc"}))
    assert scheduled["cron"] == "*/5 * * * *"
    assert queued == {"logical_id": "abc"}


def test_list_enabled_schedules_maps_postgres_rows() -> None:
    now = datetime(2026, 9, 29, tzinfo=UTC)
    row = {
        "schedule_id": "sched-1",
        "workspace_id": "w1",
        "radar_id": "r1",
        "enabled": 1,
        "cadence": CADENCE_HOURLY,
        "utc_offset_minutes": 0,
        "anchor_at": now.isoformat(),
        "max_catch_up": 3,
        "lease_seconds": 300,
        "max_attempts": 3,
        "cadence_version": "schedule-v1",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "last_planned_at": None,
    }
    conn = _Conn(rows=[row])
    store = PostgresRuntimeStore(_Connector(conn))

    schedules = _run(store.list_enabled_schedules())

    assert len(schedules) == 1
    assert schedules[0].schedule_id == "sched-1"
    assert schedules[0].workspace_id == "w1"
    assert conn.closed is True


def test_persist_plan_inserts_ticks_and_advances_watermark() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    schedule = RadarSchedule.create(
        workspace_id="w1",
        radar_id="r1",
        cadence=CADENCE_HOURLY,
        effective_from=now,
        created_at=now,
    )
    plan = plan_due(schedule, now=now)
    conn = _Conn(rows=[{"tick_id": "created"}])
    store = PostgresRuntimeStore(_Connector(conn))

    created = _run(store.persist_plan(schedule, plan, now=now))

    assert len(created) == 1
    queries = "\n".join(query for query, _ in conn.calls)
    assert "INSERT INTO trendcite.cloud_schedule_tick" in queries
    assert "ON CONFLICT (workspace_id, idempotency_key) DO NOTHING" in queries
    assert "UPDATE trendcite.cloud_radar_schedule" in queries
    assert "SET LOCAL ROLE trendcite_runtime" in queries


def _radar_run_row(run: RadarRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "workspace_id": run.workspace_id,
        "radar_id": run.radar_id,
        "radar_version_id": run.radar_version_id,
        "evaluation_cutoff": run.evaluation_cutoff.isoformat(),
        "idempotency_key": run.idempotency_key,
        "status": run.status,
        "coverage_state": run.coverage_state,
        "attempt": run.attempt,
        "signal_count": run.signal_count,
        "match_count": run.match_count,
        "error_code": run.error_code,
        "error_detail": run.error_detail,
        "started_at": run.started_at.isoformat(),
        "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
    }


def test_get_or_create_run_uses_database_idempotency_key() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    expected = RadarRun.create(
        workspace_id="w1",
        radar_id="r1",
        radar_version_id="rv1",
        evaluation_cutoff=now,
        started_at=now,
    )
    conn = _Conn(rows=[_radar_run_row(expected)], scalar="rv1")
    store = PostgresRuntimeStore(_Connector(conn))

    run = _run(
        store.get_or_create_run(
            workspace_id="w1",
            radar_id="r1",
            evaluation_cutoff=now,
            started_at=now,
        )
    )

    assert run.run_id == expected.run_id
    assert run.idempotency_key == expected.idempotency_key
    queries = "\n".join(query for query, _ in conn.calls)
    assert "FROM trendcite.cloud_radar_version" in queries
    assert "INSERT INTO trendcite.cloud_radar_run" in queries
    assert "ON CONFLICT (workspace_id, idempotency_key) DO NOTHING" in queries


def test_update_run_is_workspace_scoped() -> None:
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    run = RadarRun.create(
        workspace_id="w1",
        radar_id="r1",
        radar_version_id="rv1",
        evaluation_cutoff=now,
        started_at=now,
    ).succeeded(
        coverage_state=RUN_COVERAGE_COMPLETE,
        signal_count=4,
        match_count=2,
        finished_at=now,
    )
    conn = _Conn()
    store = PostgresRuntimeStore(_Connector(conn))

    _run(store.update_run(run))

    update = next(query for query, _ in conn.calls if "UPDATE trendcite.cloud_radar_run" in query)
    assert "WHERE workspace_id=$10 AND run_id=$11" in update
