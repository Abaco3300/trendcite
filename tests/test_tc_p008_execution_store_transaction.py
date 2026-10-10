"""Real PostgresExecutionStore control-flow tests using a fake DB boundary.

No claim of PostgreSQL or Cloudflare end-to-end integration.
"""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from trendcite.cloud.db.postgres_execution import PostgresExecutionStore


class FakeConn:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False
        self.transaction_entered = False
        self.transaction_exited = False
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        self.transaction_entered = True
        try:
            yield
        finally:
            self.transaction_exited = True

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        if self.fail:
            raise RuntimeError("synthetic adapter failure")
        return "UPDATE 0"

    async def close(self) -> None:
        self.closed = True


def test_transaction_scope_closes_on_synthetic_failure() -> None:
    conn = FakeConn(fail=True)

    async def connect() -> FakeConn:
        return conn

    store = PostgresExecutionStore(connect)
    with pytest.raises(RuntimeError, match="synthetic adapter failure"):
        store.get_run("tenant-a", "run-a").send(None)
    assert conn.transaction_entered
    assert conn.transaction_exited
    assert conn.closed
    assert conn.calls[0] == ("SET LOCAL ROLE trendcite_runtime", ())


def test_runtime_role_rejects_unsafe_identifier() -> None:
    async def connect() -> FakeConn:
        raise AssertionError("should not be called")

    with pytest.raises(ValueError, match="runtime role"):
        PostgresExecutionStore(connect, runtime_role="trendcite_runtime;DROP TABLE x")
