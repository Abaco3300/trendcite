from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trendcite.cloud.async_execution import ExecutionPersistenceBundle
from trendcite.cloud.db.postgres_execution import PostgresExecutionStore
from trendcite.cloud.domain.linked_content import RunLinkedContentEvidence
from trendcite.cloud.domain.radar import RUN_COVERAGE_COMPLETE, RadarRun


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> Tx:
        return Tx()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((" ".join(query.split()), args))
        return "UPDATE 1"

    async def close(self) -> None:
        return None


def test_linked_content_persists_only_in_supplemental_table() -> None:
    now = datetime(2026, 10, 7, 22, 30, tzinfo=UTC)
    run = RadarRun.create(
        workspace_id="ws-a",
        radar_id="radar-a",
        radar_version_id="rv-a",
        evaluation_cutoff=now,
        started_at=now,
    ).succeeded(
        coverage_state=RUN_COVERAGE_COMPLETE,
        signal_count=1,
        match_count=0,
        finished_at=now,
    )
    linked = RunLinkedContentEvidence(
        linked_content_id="lc-1",
        workspace_id="ws-a",
        run_id=run.run_id,
        signal_id="signal-a",
        bundle_id="veb-a",
        source_url="https://example.com/article",
        text_fragments=("supplemental text",),
        provenance=(),
        quality_overall=1.0,
        quality_completeness=1.0,
        quality_provenance_coverage=1.0,
        fulfilled_capabilities=("metadata", "text"),
        missing_capabilities=(),
        actual_cost_micro_usd=0,
        captured_at=now,
    )
    bundle = ExecutionPersistenceBundle(
        run=run,
        signals=(),
        signal_evaluations=(),
        relevance_evaluations=(),
        watchlist_matches=(),
        match_evaluations=(),
        matches=(),
        run_signals=(),
        coverage=(),
        usage_events=(),
        alert_candidates=(),
        linked_content=(linked,),
    )

    conn = Conn()

    async def connector() -> Conn:
        return conn

    persisted = _run(
        PostgresExecutionStore(
            connector,
            runtime_role="trendcite_nonprod_runtime",
        ).persist_execution(bundle)
    )

    assert persisted.run_id == run.run_id
    queries = [query for query, _ in conn.calls]
    linked_query = next(
        query for query in queries if "INSERT INTO trendcite.cloud_run_linked_content" in query
    )
    assert "actual_cost_micro_usd" in linked_query
    assert "ON CONFLICT (run_id, signal_id, source_url)" in linked_query
    assert not any(
        "INSERT INTO trendcite.cloud_signal " in query
        or "INSERT INTO trendcite.cloud_signal_evaluation" in query
        or "INSERT INTO trendcite.cloud_match " in query
        for query in queries
    )
