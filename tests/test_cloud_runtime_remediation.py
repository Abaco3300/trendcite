from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

from trendcite.cloud.db.postgres import PostgresRuntimeStore
from trendcite.cloud.db.postgres_execution import PostgresExecutionStore

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT_PATH = ROOT / "deploy" / "cloudflare" / "src" / "http_transport.py"


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> _Tx:
        return _Tx()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.calls.append((query, args))
        return []

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return None

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return None

    async def close(self) -> None:
        self.closed = True


class _Connector:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __call__(self) -> _Conn:
        return self.conn


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def _assert_role_precedes_select(conn: _Conn, table: str) -> None:
    sql = [query.strip() for query, _ in conn.calls]
    role_index = next(
        i for i, query in enumerate(sql) if query == "SET LOCAL ROLE trendcite_runtime"
    )
    select_index = next(i for i, query in enumerate(sql) if f"FROM {table}" in query)
    assert role_index < select_index
    assert conn.closed is True


def test_runtime_store_reads_under_runtime_role() -> None:
    conn = _Conn()
    store = PostgresRuntimeStore(_Connector(conn))

    assert _run(store.get_tick("ws-1", "tick-1")) is None

    _assert_role_precedes_select(conn, "trendcite.cloud_schedule_tick")


def test_execution_store_reads_under_runtime_role() -> None:
    conn = _Conn()
    store = PostgresExecutionStore(_Connector(conn))

    assert _run(store.get_radar_version("ws-1", "rv-1")) is None

    _assert_role_precedes_select(conn, "trendcite.cloud_radar_version")


def test_cloudflare_transport_uses_python_response_bytes(monkeypatch: Any) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    class FakeResponse:
        status = 200

        def __init__(self) -> None:
            self.headers = {"content-length": "2"}

        async def bytes(self) -> bytes:
            return b"ok"

    async def fake_fetch(url: str, *, headers: dict[str, str]) -> FakeResponse:
        calls.append((url, headers))
        return FakeResponse()

    fake_workers = types.ModuleType("workers")
    fake_workers.fetch = fake_fetch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "workers", fake_workers)

    spec = importlib.util.spec_from_file_location(
        "trendcite_cf_http_transport_test", TRANSPORT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def immediate_wait_for(awaitable: Any, *, timeout: float) -> Any:
        assert timeout == 5.0
        return await awaitable

    monkeypatch.setattr(module.asyncio, "wait_for", immediate_wait_for)

    status, body = _run(
        module.CloudflareFetchTransport()(
            "https://example.com/data",
            5.0,
            {"User-Agent": "TrendCite-test"},
        )
    )

    assert status == 200
    assert body == b"ok"
    assert calls == [("https://example.com/data", {"User-Agent": "TrendCite-test"})]

    source = TRANSPORT_PATH.read_text(encoding="utf-8")
    assert "response.bytes()" in source
    assert "arrayBuffer" not in source
    assert "Uint8Array" not in source
    assert "AbortController" not in source


def test_no_cloud_data_read_bypasses_runtime_role_transaction() -> None:
    runtime_source = (ROOT / "src" / "trendcite" / "cloud" / "db" / "postgres.py").read_text(
        encoding="utf-8"
    )
    execution_source = (
        ROOT / "src" / "trendcite" / "cloud" / "db" / "postgres_execution.py"
    ).read_text(encoding="utf-8")

    assert runtime_source.count("await self._connector()") == 2
    assert execution_source.count("await self._connector()") == 1
