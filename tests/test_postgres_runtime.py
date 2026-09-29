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

[executed on device: LAPTOP-JOSEMILE (056f59c1-dbac-4f47-875e-044865a705aa)]