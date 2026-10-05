from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trendcite.cloud.db.postgres_access import PostgresAccessStore


class Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None


class Conn:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> Tx:
        return Tx()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "SET"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.calls.append((query, args))
        return list(self.rows)

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return self.rows[0] if self.rows else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return None

    async def close(self) -> None:
        self.closed = True


class Connector:
    def __init__(self, conn: Conn) -> None:
        self.conn = conn

    async def __call__(self) -> Conn:
        return self.conn


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def row() -> dict[str, Any]:
    return {
        "workspace_id": "ws-1",
        "slug": "workspace-one",
        "name": "Workspace One",
        "role": "viewer",
        "created_at": datetime(2026, 10, 4, tzinfo=UTC),
    }


def test_list_workspaces_is_scoped_to_principal_id() -> None:
    conn = Conn([row()])
    store = PostgresAccessStore(Connector(conn))

    result = _run(store.list_workspaces("user-123"))

    assert len(result) == 1
    assert result[0].role == "viewer"
    query, args = next(
        (query, args) for query, args in conn.calls if "FROM trendcite.cloud_membership" in query
    )
    assert "WHERE m.principal_id=$1" in query
    assert args == ("user-123",)
    assert conn.closed


def test_get_workspace_requires_both_principal_and_workspace() -> None:
    conn = Conn([row()])
    store = PostgresAccessStore(Connector(conn))

    result = _run(store.get_workspace("user-123", "ws-1"))

    assert result is not None
    query, args = next(
        (query, args) for query, args in conn.calls if "FROM trendcite.cloud_membership" in query
    )
    assert "m.principal_id=$1 AND w.workspace_id=$2" in query
    assert args == ("user-123", "ws-1")


def test_get_workspace_returns_none_without_membership() -> None:
    conn = Conn([])
    store = PostgresAccessStore(Connector(conn))

    assert _run(store.get_workspace("other-user", "ws-1")) is None
