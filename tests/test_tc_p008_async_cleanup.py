"""Exercise TC-P008 asynchronous resource cleanup with a socket-free event loop."""

from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime, timedelta

import pytest

from trendcite.cloud.tc_p008_hosted_backend_overlap import attest_hosted_overlap

_NATIVE_CONNECT = socket.socket.connect


class FakeConnection:
    def __init__(self, pid: int, *, fail: bool = False) -> None:
        self.pid = pid
        self.fail = fail
        self.closed = False

    async def fetchrow(self, query: str):
        assert "pg_backend_pid()" in query
        await asyncio.sleep(0)
        if self.fail:
            raise RuntimeError("injected query failure")
        now = datetime.now(UTC)
        return {"pid": self.pid, "started_at": now, "finished_at": now + timedelta(seconds=1)}

    async def close(self) -> None:
        self.closed = True


def _run_offline(coro, monkeypatch: pytest.MonkeyPatch):
    # Windows asyncio creates its self-pipe with a loopback socketpair.
    # Allow ONLY the loopback handshake while constructing the event loop.
    blocked_connect = socket.socket.connect

    def loopback_only(sock, address):
        if not (isinstance(address, tuple) and address[0] == "127.0.0.1"):
            raise AssertionError("non-loopback network attempted during test setup")
        return _NATIVE_CONNECT(sock, address)

    with monkeypatch.context() as scoped:
        scoped.setattr(socket.socket, "connect", loopback_only)
        loop = asyncio.SelectorEventLoop()
    assert socket.socket.connect is blocked_connect
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_async_overlap_uses_two_sessions_and_closes_both(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = [FakeConnection(101), FakeConnection(102)]
    first, second = connections.copy()

    async def connector():
        return connections.pop(0)

    result = _run_offline(attest_hosted_overlap(connector), monkeypatch)
    assert result["overlap"] is True
    assert first.closed and second.closed


def test_async_overlap_error_closes_both_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    connections = [FakeConnection(101, fail=True), FakeConnection(102)]
    first, second = connections.copy()

    async def connector():
        return connections.pop(0)

    with pytest.raises(RuntimeError, match="injected query failure"):
        _run_offline(attest_hosted_overlap(connector), monkeypatch)
    assert first.closed and second.closed
