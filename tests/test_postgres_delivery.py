from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trendcite.cloud.db.postgres_delivery import PostgresDeliveryStore
from trendcite.cloud.domain.alerts import (
    ATTEMPT_SUCCEEDED,
    AlertBaseline,
    DeliveryAttempt,
    SignalState,
)

NOW = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)


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
    def __init__(self, *, rows: list[Any] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> _Tx:
        return _Tx()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "UPDATE 1"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.calls.append((query, args))
        return list(self.rows)

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.calls.append((query, args))
        return None

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


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def test_record_attempt_is_workspace_scoped_and_idempotent() -> None:
    conn = _Conn(rows=[{"attempt_id": "attempt-1"}])
    store = PostgresDeliveryStore(_Connector(conn))
    attempt = DeliveryAttempt.create(
        workspace_id="workspace-1",
        target_kind="alert",
        target_id="alert-1",
        attempt_number=1,
        channel="email",
        status=ATTEMPT_SUCCEEDED,
        provider="postmark",
        provider_reference="message-1",
        attempted_at=NOW,
    )

    inserted = _run(store.record_attempt(attempt))

    assert inserted is True
    queries = "\n".join(query for query, _ in conn.calls)
    assert "SET LOCAL ROLE trendcite_runtime" in queries
    assert "INSERT INTO trendcite.cloud_delivery_attempt" in queries
    assert "ON CONFLICT (workspace_id, target_kind, target_id, attempt_number)" in queries
    assert conn.closed


def test_upsert_baseline_uses_delivered_state_and_workspace_subject_key() -> None:
    conn = _Conn()
    store = PostgresDeliveryStore(_Connector(conn))
    state = SignalState.create(
        signal_id="signal-1",
        snapshot_id="snapshot-1",
        signal_score=82,
        relevance_score=91,
        lifecycle_state="emerging",
        velocity=0.7,
        source_count=3,
        counterevidence=(),
        observed_at=NOW,
    )
    baseline = AlertBaseline.of(
        workspace_id="workspace-1",
        watchlist_id="watchlist-1",
        signal_id="signal-1",
        alert_id="alert-1",
        state=state,
        delivered_at=NOW,
    )

    _run(store.upsert_baseline(baseline))

    queries = "\n".join(query for query, _ in conn.calls)
    assert "INSERT INTO trendcite.cloud_alert_baseline" in queries
    assert "ON CONFLICT (workspace_id, watchlist_id, signal_id)" in queries
    assert "delivered_at=EXCLUDED.delivered_at" in queries
    assert conn.closed


def test_alert_and_candidate_reads_are_tenant_scoped() -> None:
    conn = _Conn()
    store = PostgresDeliveryStore(_Connector(conn))

    assert _run(store.get_candidate("workspace-1", "candidate-1")) is None
    assert _run(store.get_alert("workspace-1", "alert-1")) is None

    queries = "\n".join(query for query, _ in conn.calls)
    assert "WHERE workspace_id=$1 AND candidate_id=$2" in queries
    assert "WHERE workspace_id=$1 AND alert_id=$2" in queries


def test_candidates_for_run_is_workspace_scoped() -> None:
    conn = _Conn(rows=[])
    store = PostgresDeliveryStore(_Connector(conn))

    assert _run(store.candidates_for_run("workspace-1", "run-1")) == ()

    query = next(
        query for query, _ in conn.calls if "FROM trendcite.cloud_alert_candidate" in query
    )
    assert "WHERE workspace_id=$1 AND run_id=$2" in query
