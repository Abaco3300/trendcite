from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from trendcite.cloud.async_scheduler import (
    AsyncRunResult,
    AsyncScheduledCoordinator,
)
from trendcite.cloud.domain.radar import RUN_FAILED, RUN_SUCCEEDED
from trendcite.cloud.domain.scheduling import (
    CADENCE_HOURLY,
    DuePlan,
    RadarSchedule,
    ScheduleTick,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _run(coro: Any) -> Any:
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("fake-only coroutine unexpectedly suspended")


def _schedule(*, max_attempts: int = 3, enabled: bool = True) -> RadarSchedule:
    return RadarSchedule.create(
        workspace_id="ws-1",
        radar_id="radar-1",
        cadence=CADENCE_HOURLY,
        effective_from=NOW,
        enabled=enabled,
        max_attempts=max_attempts,
        created_at=NOW,
    )


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, payload: dict[str, str]) -> None:
        self.sent.append(dict(payload))


class FakeRunner:
    def __init__(self, results: list[AsyncRunResult | BaseException]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, str, datetime]] = []

    async def run_radar(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
    ) -> AsyncRunResult:
        self.calls.append((workspace_id, radar_id, evaluation_cutoff))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeStore:
    def __init__(self, schedule: RadarSchedule) -> None:
        self.schedule = schedule
        self.ticks: dict[str, ScheduleTick] = {}
        self.force_claim_loss = False
        self.force_settle_loss = False

    async def list_enabled_schedules(self) -> tuple[RadarSchedule, ...]:
        return (self.schedule,) if self.schedule.enabled else ()

    async def persist_plan(
        self,
        schedule: RadarSchedule,
        plan: DuePlan,
        *,
        now: datetime,
    ) -> tuple[ScheduleTick, ...]:
        created: list[ScheduleTick] = []
        for cutoff in plan.skipped:
            tick = ScheduleTick.create(
                schedule=schedule,
                evaluation_cutoff=cutoff,
                created_at=now,
                status="skipped",
                skip_reason="catch_up_exceeded",
            )
            self.ticks.setdefault(tick.tick_id, tick)
        for cutoff in plan.due:
            tick = ScheduleTick.create(
                schedule=schedule,
                evaluation_cutoff=cutoff,
                created_at=now,
            )
            if tick.tick_id not in self.ticks:
                self.ticks[tick.tick_id] = tick
                created.append(tick)
        if plan.watermark is not None:
            self.schedule = schedule.planned_through(plan.watermark)
        return tuple(created)

    async def get_tick(self, workspace_id: str, tick_id: str) -> ScheduleTick | None:
        tick = self.ticks.get(tick_id)
        if tick is None or tick.workspace_id != workspace_id:
            return None
        return tick

    async def get_schedule(self, workspace_id: str, schedule_id: str) -> RadarSchedule | None:
        if self.schedule.workspace_id == workspace_id and self.schedule.schedule_id == schedule_id:
            return self.schedule
        return None

    async def claim_tick(
        self,
        *,
        workspace_id: str,
        tick_id: str,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        if self.force_claim_loss:
            return False
        tick = await self.get_tick(workspace_id, tick_id)
        if tick is None or not tick.claimable_at(now):
            return False
        claimed = tick.claimed(
            owner=owner,
            now=now,
            lease=lease_expires_at - now,
        )
        self.ticks[tick_id] = claimed
        return True

    async def settle_tick(
        self,
        tick: ScheduleTick,
        *,
        expected_owner: str,
    ) -> bool:
        if self.force_settle_loss:
            return False
        stored = self.ticks.get(tick.tick_id)
        if stored is None or stored.lease_owner != expected_owner:
            return False
        self.ticks[tick.tick_id] = tick
        return True


def _planned_fixture(
    *,
    max_attempts: int = 3,
    runner_results: list[AsyncRunResult | BaseException] | None = None,
) -> tuple[FakeStore, FakeQueue, FakeRunner, AsyncScheduledCoordinator, ScheduleTick]:
    store = FakeStore(_schedule(max_attempts=max_attempts))
    queue = FakeQueue()
    runner = FakeRunner(runner_results or [AsyncRunResult(run_id="run-1", status=RUN_SUCCEEDED)])
    coordinator = AsyncScheduledCoordinator(
        store,
        queue,
        runner,
        worker_id="worker-a",
    )
    planning = _run(coordinator.plan_and_enqueue(now=NOW))
    assert planning.enqueued == 1
    tick = next(iter(store.ticks.values()))
    return store, queue, runner, coordinator, tick


def test_plan_and_enqueue_is_idempotent_by_tick_identity() -> None:
    store = FakeStore(_schedule())
    queue = FakeQueue()
    coordinator = AsyncScheduledCoordinator(
        store,
        queue,
        FakeRunner([]),
        worker_id="worker-a",
    )

    first = _run(coordinator.plan_and_enqueue(now=NOW))
    second = _run(coordinator.plan_and_enqueue(now=NOW))

    assert first.enqueued == 1
    assert second.enqueued == 0
    assert len(queue.sent) == 1
    assert queue.sent[0]["logical_id"] == queue.sent[0]["tick_id"]


def test_losing_claim_on_unfinished_tick_retries_transport_instead_of_acking() -> None:
    store, _, _, coordinator, tick = _planned_fixture()
    store.force_claim_loss = True

    outcome = _run(
        coordinator.execute_message(
            {"workspace_id": tick.workspace_id, "tick_id": tick.tick_id},
            now=NOW,
        )
    )

    assert not outcome.claimed
    assert outcome.retry_transport
    assert not outcome.settled


def test_success_claims_executes_and_settles_once() -> None:
    store, queue, runner, coordinator, tick = _planned_fixture()
    before = len(queue.sent)

    outcome = _run(
        coordinator.execute_message(
            {"workspace_id": tick.workspace_id, "tick_id": tick.tick_id},
            now=NOW,
        )
    )

    assert outcome.claimed
    assert outcome.status == "succeeded"
    assert outcome.run_id == "run-1"
    assert outcome.settled
    assert not outcome.retry_transport
    assert not outcome.requeued
    assert store.ticks[tick.tick_id].status == "succeeded"
    assert len(runner.calls) == 1
    assert len(queue.sent) == before

    replay = _run(
        coordinator.execute_message(
            {"workspace_id": tick.workspace_id, "tick_id": tick.tick_id},
            now=NOW,
        )
    )
    assert not replay.claimed
    assert replay.status == "succeeded"
    assert len(runner.calls) == 1


def test_failed_run_is_settled_and_requeued_until_same_tick_succeeds() -> None:
    store, queue, runner, coordinator, tick = _planned_fixture(
        runner_results=[
            AsyncRunResult(
                run_id="run-stable",
                status=RUN_FAILED,
                error_code="Transient",
                error_detail="retry me",
            ),
            AsyncRunResult(run_id="run-stable", status=RUN_SUCCEEDED),
        ]
    )

    first = _run(
        coordinator.execute_message(
            {"workspace_id": tick.workspace_id, "tick_id": tick.tick_id},
            now=NOW,
        )
    )
    assert first.status == "failed"
    assert first.requeued
    assert store.ticks[tick.tick_id].attempt == 1
    assert len(queue.sent) == 2

    second = _run(coordinator.execute_message(queue.sent[-1], now=NOW))
    assert second.status == "succeeded"
    assert second.run_id == "run-stable"
    assert store.ticks[tick.tick_id].attempt == 2
    assert len(runner.calls) == 2


def test_exception_uses_safe_failure_and_does_not_requeue_after_attempt_budget() -> None:
    store, queue, _, coordinator, tick = _planned_fixture(
        max_attempts=1,
        runner_results=[RuntimeError("provider token must never leak")],
    )

    outcome = _run(
        coordinator.execute_message(
            {"workspace_id": tick.workspace_id, "tick_id": tick.tick_id},
            now=NOW,
        )
    )

    assert outcome.status == "failed"
    assert outcome.settled
    assert not outcome.requeued
    assert len(queue.sent) == 1
    stored = store.ticks[tick.tick_id]
    assert stored.attempt == 1
    assert stored.error_code
    assert stored.error_detail


def test_lost_lease_at_settlement_requests_transport_retry() -> None:
    store, _, _, coordinator, tick = _planned_fixture()
    store.force_settle_loss = True

    outcome = _run(
        coordinator.execute_message(
            {"workspace_id": tick.workspace_id, "tick_id": tick.tick_id},
            now=NOW,
        )
    )

    assert outcome.claimed
    assert not outcome.settled
    assert outcome.retry_transport
