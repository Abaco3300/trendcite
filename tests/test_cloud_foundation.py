from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trendcite.cloud.application import CloudApplication, ExecutionBatch
from trendcite.cloud.db.sqlite import SQLiteUnitOfWorkFactory, connect
from trendcite.cloud.domain import RUN_FAILED, RUN_SUCCEEDED
from trendcite.cloud.domain.usage import (
    USAGE_MATCH_RECORDED,
    USAGE_RADAR_RUN,
    USAGE_SIGNAL_EVALUATED,
)
from trendcite.cloud.errors import TenantIsolationError
from trendcite.models import SourceStatus
from trendcite.pipeline import run_demo

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class DemoExecutor:
    def __init__(self, statuses: tuple[SourceStatus, ...] | None = None) -> None:
        self.calls = 0
        self.statuses = statuses

    def execute(self, radar: object, *, evaluation_cutoff: datetime) -> ExecutionBatch:
        self.calls += 1
        report = run_demo(top=5)
        signals = tuple(b.signal for b in report.briefs if b.signal is not None)
        statuses = self.statuses or tuple(report.source_status)
        return ExecutionBatch(signals=signals, source_status=statuses)


class FlakyExecutor(DemoExecutor):
    def execute(self, radar: object, *, evaluation_cutoff: datetime) -> ExecutionBatch:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(r"C:\secret\runtime failed token=redacted")
        report = run_demo(top=5)
        signals = tuple(b.signal for b in report.briefs if b.signal is not None)
        return ExecutionBatch(signals=signals, source_status=tuple(report.source_status))


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "cloud.db"


def app_for(db: Path, executor: DemoExecutor | None = None) -> CloudApplication:
    factory = SQLiteUnitOfWorkFactory(db)
    factory.bootstrap()
    return CloudApplication(factory, executor=executor or DemoExecutor(), clock=Clock())


def create_radar(app: CloudApplication, slug: str = "alpha") -> tuple[str, str, str]:
    workspace = app.create_workspace(slug=slug, name=slug.title(), owner_principal_id="owner")
    watchlist, _ = app.create_watchlist(
        workspace_id=workspace.workspace_id,
        name="AI developer tools",
        include_terms=["mcp server"],
    )
    radar, _ = app.create_radar(
        workspace_id=workspace.workspace_id,
        name="Developer Radar",
        watchlist_ids=[watchlist.watchlist_id],
        sources=["hackernews", "github", "rss", "reddit"],
    )
    return workspace.workspace_id, watchlist.watchlist_id, radar.radar_id


def test_migrations_bootstrap_and_repeat(db: Path) -> None:
    factory = SQLiteUnitOfWorkFactory(db)
    first = factory.bootstrap()
    second = factory.bootstrap()
    assert first == [
        "0001_cloud_foundation.sql",
        "0002_signal_matching_relevance.sql",
    ]
    assert second == first
    conn = connect(db)
    try:
        rows = conn.execute("SELECT name FROM schema_migrations").fetchall()
        assert [row[0] for row in rows] == first
    finally:
        conn.close()


def test_workspace_membership_and_tenant_isolation(db: Path) -> None:
    app = app_for(db)
    a, _, _ = create_radar(app, "alpha")
    b, watchlist_b, _ = create_radar(app, "beta")
    assert a != b

    with SQLiteUnitOfWorkFactory(db)() as uow:
        assert len(uow.memberships.list_for_workspace(a)) == 1
        assert uow.watchlists.get(a, watchlist_b) is None
        assert uow.watchlists.get(b, watchlist_b) is not None

    with pytest.raises(TenantIsolationError):
        app.create_radar(
            workspace_id=a,
            name="Illegal Radar",
            watchlist_ids=[watchlist_b],
            sources=["hackernews"],
        )


def test_watchlist_and_radar_version_pinning(db: Path) -> None:
    app = app_for(db)
    workspace_id, watchlist_id, radar_id = create_radar(app)
    v2 = app.update_watchlist(
        workspace_id=workspace_id,
        watchlist_id=watchlist_id,
        include_terms=["term that demo does not contain"],
    )
    with SQLiteUnitOfWorkFactory(db)() as uow:
        versions = uow.watchlists.versions(workspace_id, watchlist_id)
        radar_v1 = uow.radars.latest_version(workspace_id, radar_id)
        assert [v.version_number for v in versions] == [1, 2]
        assert radar_v1 is not None
        assert radar_v1.watchlist_version_ids == (versions[0].version_id,)
        assert v2.version_id != versions[0].version_id

    run = app.run_radar(
        workspace_id=workspace_id,
        radar_id=radar_id,
        evaluation_cutoff=NOW,
    )
    assert run.status == RUN_SUCCEEDED
    assert run.match_count >= 1


def test_successful_run_is_idempotent_and_metered_once(db: Path) -> None:
    executor = DemoExecutor()
    app = app_for(db, executor)
    workspace_id, _, radar_id = create_radar(app)

    first = app.run_radar(
        workspace_id=workspace_id,
        radar_id=radar_id,
        evaluation_cutoff=NOW,
    )
    second = app.run_radar(
        workspace_id=workspace_id,
        radar_id=radar_id,
        evaluation_cutoff=NOW,
    )
    assert first.run_id == second.run_id
    assert second.status == RUN_SUCCEEDED
    assert executor.calls == 1

    with SQLiteUnitOfWorkFactory(db)() as uow:
        runs = uow.runs.list_for_radar(workspace_id, radar_id)
        evaluations = uow.matches.evaluations_for_run(workspace_id, first.run_id)
        relevance = uow.relevance.evaluations_for_run(workspace_id, first.run_id)
        matches = uow.matches.list_for_radar(workspace_id, radar_id)
        assert len(runs) == 1
        assert evaluations
        assert relevance
        assert all(item.snapshot_id for item in relevance)
        assert matches
        assert uow.usage.total(workspace_id, USAGE_RADAR_RUN) == 1
        assert uow.usage.total(workspace_id, USAGE_SIGNAL_EVALUATED) == first.signal_count
        assert uow.usage.total(workspace_id, USAGE_MATCH_RECORDED) == first.match_count


def test_failed_run_retries_same_identity_without_duplicate_usage(db: Path) -> None:
    executor = FlakyExecutor()
    app = app_for(db, executor)
    workspace_id, _, radar_id = create_radar(app)

    failed = app.run_radar(
        workspace_id=workspace_id,
        radar_id=radar_id,
        evaluation_cutoff=NOW,
    )
    assert failed.status == RUN_FAILED
    assert "<path>" in failed.error_detail

    succeeded = app.run_radar(
        workspace_id=workspace_id,
        radar_id=radar_id,
        evaluation_cutoff=NOW,
    )
    assert succeeded.status == RUN_SUCCEEDED
    assert succeeded.run_id == failed.run_id
    assert succeeded.attempt == 2
    assert executor.calls == 2

    with SQLiteUnitOfWorkFactory(db)() as uow:
        assert len(uow.runs.list_for_radar(workspace_id, radar_id)) == 1
        assert uow.usage.total(workspace_id, USAGE_RADAR_RUN) == 1


def test_degraded_coverage_is_not_zero_activity(db: Path) -> None:
    statuses = (
        SourceStatus("hackernews", True, 3, ""),
        SourceStatus("github", False, 0, "temporary failure"),
    )
    app = app_for(db, DemoExecutor(statuses))
    workspace = app.create_workspace(slug="alpha", name="Alpha", owner_principal_id="owner")
    watchlist, _ = app.create_watchlist(
        workspace_id=workspace.workspace_id,
        name="MCP",
        include_terms=["mcp server"],
    )
    radar, _ = app.create_radar(
        workspace_id=workspace.workspace_id,
        name="Radar",
        watchlist_ids=[watchlist.watchlist_id],
        sources=["hackernews", "github"],
    )
    run = app.run_radar(
        workspace_id=workspace.workspace_id,
        radar_id=radar.radar_id,
        evaluation_cutoff=NOW,
    )
    assert run.status == RUN_SUCCEEDED
    assert run.coverage_state == "degraded"

    with SQLiteUnitOfWorkFactory(db)() as uow:
        coverage = {
            c.source: c for c in uow.coverage.list_for_run(workspace.workspace_id, run.run_id)
        }
        assert coverage["hackernews"].state == "ok"
        assert coverage["github"].state == "failed"


def test_persistence_survives_restart_and_signals_are_global(db: Path) -> None:
    app = app_for(db)
    workspace_a, _, radar_a = create_radar(app, "alpha")
    workspace_b, _, radar_b = create_radar(app, "beta")
    run_a = app.run_radar(
        workspace_id=workspace_a,
        radar_id=radar_a,
        evaluation_cutoff=NOW,
    )
    run_b = app.run_radar(
        workspace_id=workspace_b,
        radar_id=radar_b,
        evaluation_cutoff=NOW,
    )

    reopened = SQLiteUnitOfWorkFactory(db)
    with reopened() as uow:
        assert uow.runs.get(workspace_a, run_a.run_id) is not None
        assert uow.runs.get(workspace_b, run_b.run_id) is not None
        signals_a = uow.signals.run_signals(workspace_a, run_a.run_id)
        signals_b = uow.signals.run_signals(workspace_b, run_b.run_id)
        assert signals_a and signals_b
        assert {s.signal_id for s in signals_a} == {s.signal_id for s in signals_b}

    conn = connect(db)
    try:
        global_count = int(conn.execute("SELECT COUNT(*) FROM cloud_signal").fetchone()[0])
        assert global_count == run_a.signal_count == run_b.signal_count
    finally:
        conn.close()


def test_matcher_exclusion_wins_over_generic_include(db: Path) -> None:
    app = app_for(db)
    workspace = app.create_workspace(slug="gamma", name="Gamma", owner_principal_id="owner")
    watchlist, _ = app.create_watchlist(
        workspace_id=workspace.workspace_id,
        name="Agents excluding MCP",
        include_terms=["server"],
        exclude_terms=["mcp server"],
    )
    radar, _ = app.create_radar(
        workspace_id=workspace.workspace_id,
        name="Exclusion Radar",
        watchlist_ids=[watchlist.watchlist_id],
        sources=["hackernews", "github", "rss", "reddit"],
    )
    run = app.run_radar(
        workspace_id=workspace.workspace_id,
        radar_id=radar.radar_id,
        evaluation_cutoff=NOW,
    )
    assert run.status == RUN_SUCCEEDED
    with SQLiteUnitOfWorkFactory(db)() as uow:
        evaluations = uow.matches.evaluations_for_run(workspace.workspace_id, run.run_id)
        mcp = [e for e in evaluations if "mcp server" in e.excluded_terms]
        assert mcp
        assert all(e.decision == "excluded" and e.strength == 0.0 for e in mcp)
