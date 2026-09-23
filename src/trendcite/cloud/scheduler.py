"""The planning half of scheduled execution: which boundaries owe work, persisted.

This module decides *when* and stops there. It never opens a source, never touches a
run and never knows that alerting exists. Everything it writes is a ``ScheduleTick``,
which is a promise that some worker should execute a radar as of an exact instant --
not a claim that anything has been executed.

The idempotency story has two layers, on purpose:

* **Tick identity** is content-addressed over (schedule, boundary), so re-planning the
  same boundary collides on a unique constraint and writes nothing. This is the
  guarantee.
* **The watermark** (``RadarSchedule.last_planned_at``) is a cursor that keeps the
  usual case cheap. It is *not* the guarantee: a watermark lost to a crashed process,
  a restored backup or a restarted scheduler costs re-derivation, never a duplicate.

That ordering is what makes the planner safe to call from anything -- a loop, a CLI
invocation, an external cron that fires twice -- without relying on the caller for
exactly-once behaviour. An external scheduler being at-least-once is assumed, not
feared.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .domain.scheduling import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_CATCH_UP,
    SKIP_CATCH_UP_EXCEEDED,
    TICK_SKIPPED,
    DuePlan,
    RadarSchedule,
    ScheduleTick,
    plan_due,
)
from .errors import NotFoundError
from .repositories import UnitOfWork, UnitOfWorkFactory

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@dataclass(frozen=True)
class PlanningResult:
    """What one planning pass wrote, stated as three disjoint lists.

    ``created`` and ``existing`` are kept apart because "we planned four boundaries"
    and "we planned four boundaries and three of them were already there" are different
    facts, and collapsing them would hide a planner that had started looping.
    """

    schedule_id: str
    workspace_id: str
    radar_id: str
    created: tuple[ScheduleTick, ...]
    existing: tuple[ScheduleTick, ...]
    skipped: tuple[ScheduleTick, ...]

    @property
    def planned(self) -> tuple[ScheduleTick, ...]:
        """Every tick this pass accounted for, whether or not it wrote it."""
        return self.created + self.existing


class RadarScheduler:
    """Application service for schedule configuration and due-work planning."""

    def __init__(self, uow_factory: UnitOfWorkFactory, *, clock: Clock = utc_now) -> None:
        self.uow_factory = uow_factory
        self.clock = clock

    # ------------------------------------------------------------------ configuration

    def set_schedule(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        cadence: str,
        effective_from: datetime | None = None,
        enabled: bool = True,
        utc_offset_minutes: int = 0,
        at_hour: int = 0,
        at_minute: int = 0,
        weekday: int = 0,
        max_catch_up: int = DEFAULT_MAX_CATCH_UP,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> RadarSchedule:
        """Create or replace one radar's schedule.

        An edit keeps the schedule's ``created_at`` and its planning watermark. Keeping
        the watermark is the point: changing the cadence must not make every boundary
        since the beginning of time newly due, and a tenant who switches from weekly to
        hourly on a Friday wants hourly from Friday, not a backfill of the week.
        """
        now = self.clock()
        with self.uow_factory() as uow:
            if uow.radars.get(workspace_id, radar_id) is None:
                raise NotFoundError("radar not found in workspace")
            existing = uow.schedules.schedule_for_radar(workspace_id, radar_id)
            schedule = RadarSchedule.create(
                workspace_id=workspace_id,
                radar_id=radar_id,
                cadence=cadence,
                effective_from=effective_from if effective_from is not None else now,
                enabled=enabled,
                utc_offset_minutes=utc_offset_minutes,
                at_hour=at_hour,
                at_minute=at_minute,
                weekday=weekday,
                max_catch_up=max_catch_up,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
                created_at=now,
            )
            if existing is not None:
                schedule = _carry_forward(schedule, existing)
            uow.schedules.upsert_schedule(schedule)
            uow.commit()
            return schedule

    def set_enabled(self, *, workspace_id: str, radar_id: str, enabled: bool) -> RadarSchedule:
        """Pause or resume a schedule without discarding what it has already done.

        Pausing writes nothing to existing ticks. Work already planned and already
        claimed is work in flight, and cancelling it here would mean the scheduler
        reaching into the executor's lane.
        """
        with self.uow_factory() as uow:
            schedule = uow.schedules.schedule_for_radar(workspace_id, radar_id)
            if schedule is None:
                raise NotFoundError("radar has no schedule in this workspace")
            updated = schedule.with_enabled(enabled, updated_at=self.clock())
            uow.schedules.upsert_schedule(updated)
            uow.commit()
            return updated

    def get_schedule(self, *, workspace_id: str, radar_id: str) -> RadarSchedule | None:
        with self.uow_factory() as uow:
            return uow.schedules.schedule_for_radar(workspace_id, radar_id)

    def ticks(self, *, workspace_id: str, schedule_id: str) -> list[ScheduleTick]:
        with self.uow_factory() as uow:
            return uow.schedules.ticks_for_schedule(workspace_id, schedule_id)

    # ---------------------------------------------------------------------- planning

    def plan(self, schedule: RadarSchedule, *, now: datetime | None = None) -> PlanningResult:
        """Persist the ticks one schedule owes as of ``now``.

        Boundaries beyond the catch-up budget are written as ``skipped`` ticks rather
        than dropped. A row saying "this boundary was passed over because the schedule
        was too far behind" is auditable; silence is not, and a gap in a tick history
        that means "we chose not to" looks exactly like a gap that means "we lost it".
        """
        instant = now if now is not None else self.clock()
        current = plan_due(schedule, now=instant)
        with self.uow_factory() as uow:
            result = self._persist(uow, schedule, current, now=instant)
            uow.commit()
        return result

    def plan_workspace(
        self, workspace_id: str, *, now: datetime | None = None
    ) -> list[PlanningResult]:
        """Plan every schedule in one workspace. Cannot see another tenant's work."""
        with self.uow_factory() as uow:
            schedules = uow.schedules.list_schedules(workspace_id)
        return [self.plan(schedule, now=now) for schedule in schedules]

    def plan_all(self, *, now: datetime | None = None) -> list[PlanningResult]:
        """Plan every enabled schedule in every workspace.

        The worker plane's entry point, and the only cross-tenant read in this module.
        Each schedule is still planned in its own transaction, so one tenant's bad row
        cannot roll back another tenant's ticks.
        """
        with self.uow_factory() as uow:
            schedules = uow.schedules.list_enabled_schedules()
        return [self.plan(schedule, now=now) for schedule in schedules]

    def _persist(
        self,
        uow: UnitOfWork,
        schedule: RadarSchedule,
        plan: DuePlan,
        *,
        now: datetime,
    ) -> PlanningResult:
        created: list[ScheduleTick] = []
        existing: list[ScheduleTick] = []
        skipped: list[ScheduleTick] = []

        for boundary in plan.skipped:
            tick = ScheduleTick.create(
                schedule=schedule,
                evaluation_cutoff=boundary,
                created_at=now,
                status=TICK_SKIPPED,
                skip_reason=SKIP_CATCH_UP_EXCEEDED,
            )
            if uow.schedules.add_tick(tick):
                skipped.append(tick)
            else:
                stored = uow.schedules.get_tick(schedule.workspace_id, tick.tick_id)
                if stored is not None:
                    skipped.append(stored)

        for boundary in plan.due:
            tick = ScheduleTick.create(
                schedule=schedule,
                evaluation_cutoff=boundary,
                created_at=now,
            )
            if uow.schedules.add_tick(tick):
                created.append(tick)
                continue
            # Already planned. Return what is stored rather than the candidate: the
            # stored row may have been claimed, executed or retried since, and the
            # caller is entitled to the real state, not to this pass's guess at it.
            stored = uow.schedules.get_tick(schedule.workspace_id, tick.tick_id)
            existing.append(stored if stored is not None else tick)

        watermark = plan.watermark
        if watermark is not None:
            uow.schedules.upsert_schedule(schedule.planned_through(watermark))

        return PlanningResult(
            schedule_id=schedule.schedule_id,
            workspace_id=schedule.workspace_id,
            radar_id=schedule.radar_id,
            created=tuple(created),
            existing=tuple(existing),
            skipped=tuple(skipped),
        )


def _carry_forward(schedule: RadarSchedule, existing: RadarSchedule) -> RadarSchedule:
    """Keep an edited schedule's history: its birth date and its planning watermark."""
    carried = replace(schedule, created_at=existing.created_at)
    if existing.last_planned_at is None:
        return carried
    return carried.planned_through(existing.last_planned_at)


def due_cutoffs(ticks: Sequence[ScheduleTick]) -> tuple[datetime, ...]:
    """The cutoffs a set of ticks covers, oldest first. A convenience for callers
    and tests that care about the grid rather than about the rows."""
    return tuple(sorted(tick.evaluation_cutoff for tick in ticks))
