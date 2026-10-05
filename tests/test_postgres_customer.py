from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from trendcite.cloud.db import postgres_customer
from trendcite.cloud.db.postgres_customer import PostgresCustomerStore
from trendcite.cloud.errors import NotFoundError, PermissionDeniedError

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
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
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self.events: list[str] = []
        self.closed = False

    def transaction(self) -> Tx:
        return Tx(self)

    async def _call(self, kind: str, query: str, args: tuple[Any, ...]) -> Any:
        compact = " ".join(query.split())
        self.calls.append((kind, compact, args))
        return self.responder(kind, compact, args)

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
        self.closed = True


def store_for(conn: Conn) -> PostgresCustomerStore:
    async def connector() -> Conn:
        return conn

    return PostgresCustomerStore(connector, runtime_role="trendcite_nonprod_runtime")


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def membership(role: str | None) -> Responder:
    def respond(kind: str, query: str, args: tuple[Any, ...]) -> Any:
        if "FROM trendcite.cloud_membership" in query:
            return role
        return None

    return respond


def test_non_member_fails_before_workspace_data_query() -> None:
    conn = Conn(membership(None))
    with pytest.raises(NotFoundError):
        _run(store_for(conn).list_watchlists("user-b", "ws-a"))
    assert not any("cloud_watchlist AS w" in q for _, q, _ in conn.calls)
    assert conn.events == ["BEGIN", "ROLLBACK"]


def test_membership_and_data_query_share_one_transaction() -> None:
    conn = Conn(membership("viewer"))
    assert _run(store_for(conn).list_alerts("user-a", "ws-a")) == []
    queries = [q for _, q, _ in conn.calls]
    membership_index = next(i for i, q in enumerate(queries) if "cloud_membership" in q)
    data_index = next(i for i, q in enumerate(queries) if "cloud_alert AS a" in q)
    assert membership_index < data_index
    assert conn.events == ["BEGIN", "COMMIT"]


def test_viewer_write_is_denied_before_insert() -> None:
    conn = Conn(membership("viewer"))
    with pytest.raises(PermissionDeniedError):
        _run(store_for(conn).create_watchlist("u", "ws-a", name="W", include_terms=["ai"], now=NOW))
    assert not any("INSERT INTO" in q for _, q, _ in conn.calls)


def test_create_watchlist_writes_only_authorized_workspace() -> None:
    def responder(kind: str, query: str, args: tuple[Any, ...]) -> Any:
        if "cloud_membership" in query:
            return "owner"
        if query.startswith("INSERT INTO trendcite.cloud_watchlist "):
            return "wl"
        if query.startswith("INSERT INTO trendcite.cloud_watchlist_version "):
            return "v1"
        return None

    conn = Conn(responder)
    result = _run(
        store_for(conn).create_watchlist("u", "ws-a", name="W", include_terms=["ai"], now=NOW)
    )
    assert result["name"] == "W"
    inserts = [args for _, q, args in conn.calls if q.startswith("INSERT INTO")]
    assert all("ws-a" in args for args in inserts)


def test_radar_cannot_reference_watchlist_from_other_workspace() -> None:
    def responder(kind: str, query: str, args: tuple[Any, ...]) -> Any:
        if "cloud_membership" in query:
            return "owner"
        if "FROM trendcite.cloud_watchlist_version" in query:
            return None
        return None

    conn = Conn(responder)
    with pytest.raises(NotFoundError):
        _run(
            store_for(conn).create_radar(
                "u", "ws-a", name="R", watchlist_ids=["foreign"], sources=["github"], now=NOW
            )
        )
    assert not any("INSERT INTO trendcite.cloud_radar " in q for _, q, _ in conn.calls)


def test_tenant_sql_and_source_have_static_isolation_guards() -> None:
    source = Path(postgres_customer.__file__).read_text(encoding="utf-8")
    assert "user_metadata" not in source
    assert "DELETE FROM" not in source
    assert "UPDATE trendcite" not in source
    assert "WHERE principal_id=$1 AND workspace_id=$2" in source
    assert "WHERE workspace_id=$1" in source
