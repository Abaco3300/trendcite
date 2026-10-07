from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from trendcite.cloud.db.postgres_entitlements import PostgresEntitlementStore
from trendcite.cloud.domain.entitlements import CAP_RADAR_RUN
from trendcite.cloud.errors import NotFoundError

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)
Responder = Callable[[str, str, tuple[Any, ...]], Any]


class Tx:
    def __init__(self, conn: Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> None:
        self.conn.events.append("BEGIN")

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.conn.events.append("ROLLBACK" if exc_type else "COMMIT")


class Conn:
    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.events: list[str] = []
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    def transaction(self) -> Tx:
        return Tx(self)

    async def execute(self, query: str, *args: Any) -> str:
        await self._call("execute", query, args)
        return "OK"

    async def fetch(self, query: str, *args: Any) -> Any:
        return (await self._call("fetch", query, args)) or []

    async def fetchrow(self, query: str, *args: Any) -> Any:
        return await self._call("fetchrow", query, args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._call("fetchval", query, args)

    async def close(self) -> None:
        return None

    async def _call(self, kind: str, query: str, args: tuple[Any, ...]) -> Any:
        compact = " ".join(query.split())
        self.calls.append((kind, compact, args))
        return self.responder(kind, compact, args)


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def _store(conn: Conn) -> PostgresEntitlementStore:
    async def connector() -> Conn:
        return conn

    return PostgresEntitlementStore(connector, runtime_role="trendcite_nonprod_runtime")


def _plan_row(*, limit: int | None = 10) -> dict[str, Any]:
    quotas = {} if limit is None else {CAP_RADAR_RUN: {"kind": "radar_run", "limit": limit}}
    return {
        "plan_key": "nonprod_limited" if limit is not None else "nonprod_full",
        "display_name": "Nonprod",
        "capabilities": '{"radar_run":true}',
        "quotas": __import__("json").dumps(quotas, separators=(",", ":")),
    }


def test_missing_entitlement_fails_closed() -> None:
    conn = Conn(lambda kind, query, args: None)
    decision = _run(_store(conn).resolve_capability("ws", CAP_RADAR_RUN, at=NOW))
    assert decision.allowed is False
    assert decision.reason == "missing_entitlement"


def test_quota_allows_when_usage_below_limit() -> None:
    def responder(kind: str, query: str, args: tuple[Any, ...]) -> Any:
        if "FROM trendcite.cloud_workspace_entitlement" in query:
            return _plan_row(limit=10)
        if "SUM(quantity)" in query:
            return 7
        return None

    decision = _run(_store(Conn(responder)).resolve_capability("ws", CAP_RADAR_RUN, at=NOW))
    assert decision.allowed is True
    assert decision.used == 7
    assert decision.remaining == 3


def test_quota_exhaustion_denies() -> None:
    def responder(kind: str, query: str, args: tuple[Any, ...]) -> Any:
        if "FROM trendcite.cloud_workspace_entitlement" in query:
            return _plan_row(limit=10)
        if "SUM(quantity)" in query:
            return 10
        return None

    decision = _run(_store(Conn(responder)).resolve_capability("ws", CAP_RADAR_RUN, at=NOW))
    assert decision.allowed is False
    assert decision.reason == "quota_exhausted"
    assert decision.remaining == 0


def test_unlimited_capability_skips_usage_query() -> None:
    conn = Conn(
        lambda kind, query, args: (
            _plan_row(limit=None) if "cloud_workspace_entitlement" in query else None
        )
    )
    decision = _run(_store(conn).resolve_capability("ws", CAP_RADAR_RUN, at=NOW))
    assert decision.allowed is True
    assert not any("SUM(quantity)" in query for _, query, _ in conn.calls)


def test_customer_summary_requires_membership_before_entitlement() -> None:
    def responder(kind: str, query: str, args: tuple[Any, ...]) -> Any:
        if query.startswith("SET LOCAL ROLE"):
            return None
        if "FROM trendcite.cloud_membership" in query:
            return None
        raise AssertionError("entitlement query should not execute")

    conn = Conn(responder)
    with pytest.raises(NotFoundError):
        _run(_store(conn).summary_for_principal("principal", "foreign", at=NOW))
    assert conn.events == ["BEGIN", "ROLLBACK"]
