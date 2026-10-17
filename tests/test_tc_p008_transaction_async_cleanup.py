"""Offline async attestation of transaction-scoped advisory lock behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from tests.test_tc_p008_async_cleanup import _run_offline
from trendcite.cloud.tc_p008_transaction_contention import attest_transaction_lock_contention


class FakeConnection:
    def __init__(self, pid: int, *, blocked: bool) -> None:
        self.pid = pid
        self.blocked = blocked
        self.closed = False
        self.transaction_exited = False

    @asynccontextmanager
    async def transaction(self):
        try:
            yield self
        finally:
            self.transaction_exited = True

    async def fetchval(self, sql: str, *args):
        if "pg_backend_pid" in sql:
            return self.pid
        if "pg_try_advisory_xact_lock" in sql:
            return not self.blocked
        if "pg_advisory_xact_lock" in sql:
            return None
        raise AssertionError("unexpected SQL")

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("blocked", [True, False])
def test_transaction_contention_async_cleanup(
    blocked: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    holder = FakeConnection(101, blocked=False)
    contender = FakeConnection(102, blocked=blocked)
    connections = [holder, contender]

    async def connector():
        return connections.pop(0)

    if blocked:
        result = _run_offline(attest_transaction_lock_contention(connector), monkeypatch)
        assert result["concurrent_transaction_lock_contention"] is True
        assert result["unique_key_write_contention"] == "NOT_VERIFIED"
    else:
        with pytest.raises(RuntimeError, match="not established"):
            _run_offline(attest_transaction_lock_contention(connector), monkeypatch)

    assert holder.closed and contender.closed
    assert holder.transaction_exited and contender.transaction_exited
