from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trendcite.cloud.alert_runtime import AlertDigestRuntime
from trendcite.cloud.application import CloudApplication, ExecutionBatch
from trendcite.cloud.db.sqlite import SQLiteUnitOfWorkFactory
from trendcite.cloud.delivery import LocalDeliveryAdapter
from trendcite.cloud.domain.radar import RUN_COVERAGE_DEGRADED, RUN_FAILED, RUN_SUCCEEDED
from trendcite.cloud.domain.scheduling import CADENCE_HOURLY, TICK_FAILED, TICK_SUCCEEDED
from trendcite.cloud.domain.usage import USAGE_SCHEDULED_TICK
from trendcite.cloud.orchestration import ScheduledRadarOrchestrator
from trendcite.cloud.scheduler import RadarScheduler
from trendcite.models import SourceStatus
from trendcite.pipeline import run_demo

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class DemoExecutor:
    def __init__(self, statuses: tuple[SourceStatus, ...] | None = None) -> None:
        self.calls = 0
        self.statuses = statuses

    def execute(self, radar: object, *, evaluation_cutoff: datetime) -> ExecutionBatch:
        self.calls += 1
        report = run_demo(top=5)
        signals = tuple(b.signal for b in report.briefs if b.signal is not None)
        return ExecutionBatch(
            signals=signals,
            source_status=self.statuses or tuple(report.source_status),
        )


class FlakyExecutor(DemoExecutor):
    def execute(self, radar: object, *, evaluation_cutoff: datetime) -> ExecutionBatch:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient scheduled executor failure")
        report = run_demo(top=5)
        signals = tuple(b.signal for b in report.briefs if b.signal is not None)
        return ExecutionBatch(signals=signals, source_status=tuple(report.source_status))


def create_scope(
    app: CloudApplication,
    *,
    slug: str = "alpha",
    sources: tuple[str, ...] = ("hackernews", "github", "rss", "reddit"),
) -> tuple[str, str, str]:
    workspace = app.create_workspace(slug=slug, name=slug.title(), owner_principal_id="owner")
    watchlist, _ = app.create_watchlist(
        workspace_id=workspace.workspace_id,
        name="MCP",
        include_terms=["mcp server"],
    )
    radar, _ = app.create_radar(
        workspace_id=workspace.workspace_id,
        name="Radar",
        watchlist_ids=[watchlist.watchlist_id],
        sources=sources,
    )
    return workspace.workspace_id, watchlist.watchlist_id, radar.radar_id


def scheduled_fixture(
    db: Path,
    *,
    executor: DemoExecutor | None = None,
    alerting: AlertDigestRuntime | None = None,
    slug: str = "alpha",
    sources: tuple[str, ...] = ("hackernews", "github", "rss", "reddit"),
):
    factory = SQLiteUnitOfWorkFactory(db)
    factory.bootstrap()
    clock = FixedClock()
    actual_executor = executor or DemoExecutor()
    app = CloudApplication(
        factory,
        executor=actual_executor,
        alerting=alerting,
        clock=clock,
    )
    workspace_id, watchlist_id, radar_id = create_scope(app, slug=slug, sources=sources)
    scheduler = RadarScheduler(factory, clock=clock)
    schedule = scheduler.set_schedule(
        workspace_id=workspace_id,
        radar_id=radar_id,
        cadence=CADENCE_HOURLY,
        effective_from=NOW,
        max_catch_up=3,
        lease_seconds=300,
        max_attempts=3,
    )
    planned = scheduler.plan(schedule, now=NOW)
    assert len(planned.created) == 1
    return (
        factory,
        clock,
        actual_executor,
        app,
        scheduler,
        workspace_id,
        watchlist_id,
        radar_id,
        schedule,
        planned.created[0],
    )


def test_persistence_restart_and_same_tick_is_not_created_twice(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    (
        factory,
        _,
        _,
        _,
        _,
        workspace_id,
        _,
        radar_id,
        schedule,
        tick,
    ) = scheduled_fixture(db)

    restarted = RadarScheduler(SQLiteUnitOfWorkFactory(db), clock=FixedClock())
    loaded = restarted.get_schedule(workspace_id=workspace_id, radar_id=radar_id)
    assert loaded is not None
    assert loaded.schedule_id == schedule.schedule_id
    again = restarted.plan(loaded, now=NOW)
    assert again.created == ()
    assert again.existing == ()
    ticks = restarted.ticks(workspace_id=workspace_id, schedule_id=schedule.schedule_id)
    assert [item.tick_id for item in ticks] == [tick.tick_id]

    with factory() as uow:
        assert (
            uow.schedules.tick_by_idempotency_key(workspace_id, tick.idempotency_key).tick_id
            == tick.tick_id
        )


def test_atomic_claim_blocks_second_worker_and_expired_lease_is_reclaimable(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    (
        factory,
        _,
        _,
        _,
        _,
        workspace_id,
        _,
        _,
        _,
        tick,
    ) = scheduled_fixture(db)
    expires = NOW + timedelta(minutes=5)

    with factory() as uow:
        first = uow.schedules.claim_tick(
            workspace_id,
            tick.tick_id,
            owner="worker-a",
            now=NOW.isoformat(),
            lease_expires_at=expires.isoformat(),
        )
        uow.commit()
    assert first

    with factory() as uow:
        second = uow.schedules.claim_tick(
            workspace_id,
            tick.tick_id,
            owner="worker-b",
            now=(NOW + timedelta(minutes=1)).isoformat(),
            lease_expires_at=(NOW + timedelta(minutes=6)).isoformat(),
        )
        uow.commit()
    assert not second

    reclaimed_at = NOW + timedelta(minutes=6)
    with factory() as uow:
        reclaimed = uow.schedules.claim_tick(
            workspace_id,
            tick.tick_id,
            owner="worker-b",
            now=reclaimed_at.isoformat(),
            lease_expires_at=(reclaimed_at + timedelta(minutes=5)).isoformat(),
        )
        uow.commit()
        stored = uow.schedules.get_tick(workspace_id, tick.tick_id)
    assert reclaimed
    assert stored is not None
    assert stored.lease_owner == "worker-b"
    assert stored.attempt == 2


def test_scheduled_execution_uses_one_radar_run_and_cannot_reexecute_completed_tick(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    executor = DemoExecutor()
    (
        factory,
        clock,
        _,
        app,
        scheduler,
        workspace_id,
        _,
        radar_id,
        _,
        tick,
    ) = scheduled_fixture(db, executor=executor)
    worker = ScheduledRadarOrchestrator(
        factory,
        app,
        scheduler=scheduler,
        worker_id="worker-a",
        clock=clock,
    )

    first = worker.execute_tick(workspace_id, tick.tick_id)
    assert first.claimed
    assert first.run is not None
    assert first.run.status == RUN_SUCCEEDED
    assert first.tick.status == TICK_SUCCEEDED

    second = worker.execute_tick(workspace_id, tick.tick_id)
    assert not second.claimed
    assert executor.calls == 1

    with factory() as uow:
        runs = uow.runs.list_for_radar(workspace_id, radar_id)
        stored = uow.schedules.get_tick(workspace_id, tick.tick_id)
        assert len(runs) == 1
        assert stored is not None
        assert stored.run_id == runs[0].run_id == first.run.run_id
        assert uow.usage.total(workspace_id, USAGE_SCHEDULED_TICK) == 1


def test_failed_tick_retries_same_radar_run_identity_without_duplicate_run(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    executor = FlakyExecutor()
    (
        factory,
        clock,
        _,
        app,
        scheduler,
        workspace_id,
        _,
        radar_id,
        _,
        tick,
    ) = scheduled_fixture(db, executor=executor)
    worker = ScheduledRadarOrchestrator(
        factory,
        app,
        scheduler=scheduler,
        worker_id="worker-a",
        clock=clock,
    )

    first = worker.execute_tick(workspace_id, tick.tick_id)
    assert first.run is not None
    assert first.run.status == RUN_FAILED
    assert first.tick.status == TICK_FAILED

    second = worker.execute_tick(workspace_id, tick.tick_id)
    assert second.run is not None
    assert second.run.status == RUN_SUCCEEDED
    assert second.tick.status == TICK_SUCCEEDED
    assert second.tick.attempt == 2
    assert second.run.run_id == first.run.run_id
    assert executor.calls == 2

    with factory() as uow:
        assert len(uow.runs.list_for_radar(workspace_id, radar_id)) == 1
        assert uow.usage.total(workspace_id, USAGE_SCHEDULED_TICK) == 1


def test_scheduled_degraded_run_is_a_successful_tick(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    statuses = (
        SourceStatus("hackernews", True, 3, ""),
        SourceStatus("github", False, 0, "temporary failure"),
    )
    executor = DemoExecutor(statuses)
    (
        factory,
        clock,
        _,
        app,
        scheduler,
        workspace_id,
        _,
        _,
        _,
        tick,
    ) = scheduled_fixture(
        db,
        executor=executor,
        sources=("hackernews", "github"),
    )
    worker = ScheduledRadarOrchestrator(
        factory,
        app,
        scheduler=scheduler,
        worker_id="worker-a",
        clock=clock,
    )
    outcome = worker.execute_tick(workspace_id, tick.tick_id)
    assert outcome.run is not None
    assert outcome.run.status == RUN_SUCCEEDED
    assert outcome.run.coverage_state == RUN_COVERAGE_DEGRADED
    assert outcome.tick.status == TICK_SUCCEEDED


def test_tenant_scope_prevents_cross_workspace_schedule_and_tick_reads(tmp_path: Path) -> None:
    db = tmp_path / "cloud.db"
    factory = SQLiteUnitOfWorkFactory(db)
    factory.bootstrap()
    clock = FixedClock()
    app = CloudApplication(factory, executor=DemoExecutor(), clock=clock)
    ws_a, _, radar_a = create_scope(app, slug="alpha")
    ws_b, _, radar_b = create_scope(app, slug="beta")
    scheduler = RadarScheduler(factory, clock=clock)
    schedule_a = scheduler.set_schedule(
        workspace_id=ws_a,
        radar_id=radar_a,
        cadence=CADENCE_HOURLY,
        effective_from=NOW,
    )
    schedule_b = scheduler.set_schedule(
        workspace_id=ws_b,
        radar_id=radar_b,
        cadence=CADENCE_HOURLY,
        effective_from=NOW,
    )
    tick_a = scheduler.plan(schedule_a, now=NOW).created[0]
    tick_b = scheduler.plan(schedule_b, now=NOW).created[0]

    with factory() as uow:
        assert uow.schedules.get_schedule(ws_b, schedule_a.schedule_id) is None
        assert uow.schedules.get_tick(ws_b, tick_a.tick_id) is None
        assert uow.schedules.get_schedule(ws_a, schedule_b.schedule_id) is None
        assert uow.schedules.get_tick(ws_a, tick_b.tick_id) is None


def test_real_alert_digest_runtime_is_reached_through_scheduled_cloud_run(
    tmp_path: Path,
) -> None:
    db = tmp_path / "cloud.db"
    factory = SQLiteUnitOfWorkFactory(db)
    factory.bootstrap()
    clock = FixedClock()
    adapter = LocalDeliveryAdapter()
    alerting = AlertDigestRuntime(factory, adapter, clock=clock)
    executor = DemoExecutor()
    app = CloudApplication(
        factory,
        executor=executor,
        alerting=alerting,
        clock=clock,
    )
    workspace_id, _, radar_id = create_scope(app)
    scheduler = RadarScheduler(factory, clock=clock)
    schedule = scheduler.set_schedule(
        workspace_id=workspace_id,
        radar_id=radar_id,
        cadence=CADENCE_HOURLY,
        effective_from=NOW,
    )
    tick = scheduler.plan(schedule, now=NOW).created[0]
    worker = ScheduledRadarOrchestrator(
        factory,
        app,
        scheduler=scheduler,
        worker_id="worker-a",
        clock=clock,
    )

    outcome = worker.execute_tick(workspace_id, tick.tick_id)
    assert outcome.run is not None
    assert outcome.run.status == RUN_SUCCEEDED
    assert outcome.run.match_count >= 1

    with factory() as uow:
        candidates = uow.alerts.candidates_for_run(workspace_id, outcome.run.run_id)
    assert candidates
    assert adapter.delivered

    before_candidates = len(candidates)
    before_deliveries = len(adapter.delivered)
    replay = worker.execute_tick(workspace_id, tick.tick_id)
    assert not replay.claimed
    with factory() as uow:
        assert (
            len(uow.alerts.candidates_for_run(workspace_id, outcome.run.run_id))
            == before_candidates
        )
    assert len(adapter.delivered) == before_deliveries
