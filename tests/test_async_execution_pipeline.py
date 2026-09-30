from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from trendcite.cloud.application import ExecutionBatch
from trendcite.cloud.async_execution import AsyncExecutionPipelineImpl
from trendcite.cloud.domain.alerts import REASON_DELIVERY_DISABLED, AlertPolicy
from trendcite.cloud.domain.radar import (
    RUN_COVERAGE_COMPLETE,
    RUN_COVERAGE_DEGRADED,
    RUN_SUCCEEDED,
    RadarRun,
    RadarVersion,
)
from trendcite.cloud.domain.relevance import (
    BAND_VERY_STRONG,
    CONFIDENCE_HIGH,
    DECISION_MATCHED,
    RelevanceOutcome,
)
from trendcite.cloud.domain.watchlist import WatchlistVersion
from trendcite.cloud.errors import TenantIsolationError
from trendcite.models import SourceStatus
from trendcite.pipeline import run_demo

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


class FakeRelevance:
    def evaluate_one(self, watchlist: WatchlistVersion, target: Any) -> RelevanceOutcome:
        return RelevanceOutcome(
            score=90.0,
            band=BAND_VERY_STRONG,
            confidence=CONFIDENCE_HIGH,
            decision=DECISION_MATCHED,
            components=(),
            reasons=(),
        )


class FakeExecutor:
    def __init__(self, *, degraded: bool = False) -> None:
        report = run_demo(top=3)
        self.signals = tuple(brief.signal for brief in report.briefs if brief.signal is not None)
        statuses = list(report.source_status)
        if degraded and statuses:
            statuses[0] = SourceStatus(statuses[0].source, False, 0, "synthetic failure")
        self.batch = ExecutionBatch(signals=self.signals, source_status=tuple(statuses))
        self.calls = 0

    async def execute(
        self,
        radar: RadarVersion,
        *,
        evaluation_cutoff: datetime,
    ) -> ExecutionBatch:
        self.calls += 1
        return self.batch


class FakeStore:
    def __init__(
        self,
        radar: RadarVersion,
        watchlist: WatchlistVersion,
        *,
        policy: AlertPolicy | None = None,
    ) -> None:
        self.radar = radar
        self.watchlist = watchlist
        self.watchlists = {watchlist.version_id: watchlist}
        self.policy = policy
        self.bundle: Any = None

    async def get_radar_version(self, workspace_id: str, version_id: str) -> RadarVersion | None:
        if self.radar.workspace_id == workspace_id and self.radar.version_id == version_id:
            return self.radar
        return None

    async def get_watchlist_version(
        self, workspace_id: str, version_id: str
    ) -> WatchlistVersion | None:
        value = self.watchlists.get(version_id)
        if value is not None and value.workspace_id == workspace_id:
            return value
        return None

    async def get_watchlist_signal_match(
        self,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
    ) -> None:
        return None

    async def get_match(
        self,
        workspace_id: str,
        radar_id: str,
        signal_id: str,
    ) -> None:
        return None

    async def get_alert_policy(self, workspace_id: str, radar_id: str) -> AlertPolicy | None:
        return self.policy

    async def get_alert_baseline(
        self,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
    ) -> None:
        return None

    async def persist_execution(self, bundle: Any) -> RadarRun:
        self.bundle = bundle
        return bundle.run


def _fixture(
    *,
    policy: AlertPolicy | None = None,
    degraded: bool = False,
) -> tuple[FakeStore, FakeExecutor, AsyncExecutionPipelineImpl, RadarRun]:
    watchlist = WatchlistVersion.create(
        watchlist_id="watch-1",
        workspace_id="ws-1",
        version_number=1,
        include_terms=["synthetic"],
        created_at=NOW,
    )
    radar = RadarVersion.create(
        radar_id="radar-1",
        workspace_id="ws-1",
        version_number=1,
        watchlist_version_ids=[watchlist.version_id],
        sources=["hackernews", "github", "rss", "reddit"],
        niche=["ai"],
        top=3,
        created_at=NOW,
    )
    run = RadarRun.create(
        workspace_id="ws-1",
        radar_id=radar.radar_id,
        radar_version_id=radar.version_id,
        evaluation_cutoff=NOW,
        started_at=NOW,
    )
    store = FakeStore(radar, watchlist, policy=policy)
    executor = FakeExecutor(degraded=degraded)
    pipeline = AsyncExecutionPipelineImpl(
        store,
        executor,
        relevance=FakeRelevance(),
    )
    return store, executor, pipeline, run


def test_pipeline_builds_and_persists_complete_execution_bundle() -> None:
    store, executor, pipeline, run = _fixture()

    finished = _run(pipeline.execute_and_persist(run))

    assert finished.status == RUN_SUCCEEDED
    assert finished.coverage_state == RUN_COVERAGE_COMPLETE
    assert executor.calls == 1
    bundle = store.bundle
    assert bundle is not None
    assert len(bundle.signals) == 3
    assert len(bundle.signal_evaluations) == 3
    assert len(bundle.relevance_evaluations) == 3
    assert len(bundle.match_evaluations) == 3
    assert len(bundle.watchlist_matches) == 3
    assert len(bundle.matches) == 3
    assert len(bundle.run_signals) == 3
    assert len(bundle.coverage) == 4
    assert len(bundle.alert_candidates) == 3
    assert all(candidate.qualified for candidate in bundle.alert_candidates)
    assert {event.kind for event in bundle.usage_events} >= {
        "radar_run",
        "signal_evaluated",
        "match_recorded",
        "alert_candidate",
    }


def test_pipeline_persists_suppressed_candidates_and_usage() -> None:
    policy = AlertPolicy.create(
        workspace_id="ws-1",
        radar_id="radar-1",
        updated_at=NOW,
        enabled=False,
    )
    store, _, pipeline, run = _fixture(policy=policy)

    _run(pipeline.execute_and_persist(run))

    bundle = store.bundle
    assert bundle is not None
    assert bundle.alert_candidates
    assert all(
        candidate.reason == REASON_DELIVERY_DISABLED for candidate in bundle.alert_candidates
    )
    assert "alert_suppressed" in {event.kind for event in bundle.usage_events}


def test_degraded_source_coverage_is_preserved_on_succeeded_run() -> None:
    store, _, pipeline, run = _fixture(degraded=True)

    finished = _run(pipeline.execute_and_persist(run))

    assert finished.status == RUN_SUCCEEDED
    assert finished.coverage_state == RUN_COVERAGE_DEGRADED
    assert store.bundle.run.coverage_state == RUN_COVERAGE_DEGRADED


def test_pipeline_rejects_cross_workspace_missing_watchlist_pin() -> None:
    store, _, pipeline, run = _fixture()
    store.watchlist = WatchlistVersion.create(
        watchlist_id="watch-other",
        workspace_id="ws-other",
        version_number=1,
        include_terms=["synthetic"],
        created_at=NOW,
    )
    store.watchlists = {store.watchlist.version_id: store.watchlist}

    with pytest.raises(TenantIsolationError):
        _run(pipeline.execute_and_persist(run))


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: Any, exc: BaseException | None, tb: Any) -> None:
        return None


class _DbConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> _Tx:
        return _Tx()

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append((query, args))
        return "UPDATE 1"

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


class _DbConnector:
    def __init__(self, conn: _DbConn) -> None:
        self.conn = conn

    async def __call__(self) -> _DbConn:
        return self.conn


def test_postgres_execution_persists_all_bundle_families_in_one_transaction() -> None:
    from trendcite.cloud.db.postgres_execution import PostgresExecutionStore

    capture, _, pipeline, run = _fixture()
    _run(pipeline.execute_and_persist(run))
    bundle = capture.bundle
    assert bundle is not None

    conn = _DbConn()
    store = PostgresExecutionStore(_DbConnector(conn))
    persisted = _run(store.persist_execution(bundle))

    assert persisted.run_id == run.run_id
    assert conn.closed
    sql = "\n".join(query for query, _ in conn.calls)
    for table in (
        "trendcite.cloud_signal",
        "trendcite.cloud_signal_evaluation",
        "trendcite.cloud_relevance_evaluation",
        "trendcite.cloud_relevance_evaluation_run",
        "trendcite.cloud_watchlist_signal_match",
        "trendcite.cloud_match_evaluation",
        "trendcite.cloud_match",
        "trendcite.cloud_run_signal",
        "trendcite.cloud_run_coverage",
        "trendcite.cloud_alert_candidate",
        "trendcite.cloud_usage_event",
        "trendcite.cloud_radar_run",
    ):
        assert table in sql
    assert "SET LOCAL ROLE trendcite_runtime" in sql
    assert "ON CONFLICT (workspace_id, dedupe_key) DO NOTHING" in sql
    assert "ON CONFLICT (snapshot_id) DO NOTHING" in sql


def test_multiple_watchlists_preserve_strongest_radar_match_in_same_run() -> None:
    class VaryingRelevance:
        def evaluate_one(self, watchlist: WatchlistVersion, target: Any) -> RelevanceOutcome:
            score = 60.0 if watchlist.version_number == 1 else 95.0
            return RelevanceOutcome(
                score=score,
                band=BAND_VERY_STRONG,
                confidence=CONFIDENCE_HIGH,
                decision=DECISION_MATCHED,
                components=(),
                reasons=(),
            )

    first = WatchlistVersion.create(
        watchlist_id="watch-1",
        workspace_id="ws-1",
        version_number=1,
        include_terms=["synthetic"],
        created_at=NOW,
    )
    second = WatchlistVersion.create(
        watchlist_id="watch-2",
        workspace_id="ws-1",
        version_number=2,
        include_terms=["synthetic"],
        created_at=NOW,
    )
    radar = RadarVersion.create(
        radar_id="radar-1",
        workspace_id="ws-1",
        version_number=1,
        watchlist_version_ids=[first.version_id, second.version_id],
        sources=["hackernews", "github", "rss", "reddit"],
        niche=["ai"],
        top=3,
        created_at=NOW,
    )
    run = RadarRun.create(
        workspace_id="ws-1",
        radar_id=radar.radar_id,
        radar_version_id=radar.version_id,
        evaluation_cutoff=NOW,
        started_at=NOW,
    )
    store = FakeStore(radar, first)
    store.watchlists = {
        first.version_id: first,
        second.version_id: second,
    }
    pipeline = AsyncExecutionPipelineImpl(
        store,
        FakeExecutor(),
        relevance=VaryingRelevance(),
    )

    _run(pipeline.execute_and_persist(run))

    bundle = store.bundle
    assert bundle is not None
    assert len(bundle.matches) == 3
    assert all(match.strength == 0.95 for match in bundle.matches)
