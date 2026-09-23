"""The executing half of scheduled execution: claim a tick, run the radar, settle.

The orchestrator is deliberately thin, and what it *refuses* to do is the design:

* It does not execute a radar. It calls :meth:`CloudApplication.run_radar` with the
  tick's cutoff and lets run identity do its job. Two ticks on one boundary, a retry,
  a restart and a duplicate external trigger all resolve to the same logical
  ``RadarRun``, which is why none of them can duplicate signals, matches or alerts.
* It does not qualify, render or deliver anything. Alerting already hangs off
  ``CloudApplication``'s alerting hook, so a scheduled run alerts by exactly the same
  path a manual one does. There is no second alerting entry point to keep in step.
* It does not decide when. That was the scheduler's job, and the cutoff it executes
  is the boundary the scheduler wrote, never ``now``. A tick claimed eleven minutes
  late still evaluates the radar as of its boundary.

Resumability rests on a lease rather than on a heartbeat. A worker takes a tick with
an expiry; if the process dies, nothing is cleaned up and nothing is detected -- the
lease simply lapses, and the next sweep finds the tick claimable again. The cost of an
interrupted worker is therefore bounded by the lease, and the price of a crash is at
worst one re-execution of a run that is itself idempotent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .application import CloudApplication
from .domain.radar import RUN_SUCCEEDED, RadarRun
from .domain.scheduling import (
    SKIP_SCHEDULE_DISABLED,
    RadarSchedule,
    ScheduleTick,
)
from .domain.usage import USAGE_SCHEDULED_TICK, UsageEvent, entity_dedupe_key
from .errors import NotFoundError, safe_error
from .repositories import UnitOfWork, UnitOfWorkFactory
from .scheduler import PlanningResult, RadarScheduler

Clock = Callable[[], datetime]

#: How many ticks one sweep will claim. A bound rather than a tuning knob: a worker
#: that drains an unbounded backlog in one pass holds its lease for an unbounded time.
DEFAULT_BATCH_SIZE = 20


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@dataclass(frozen=True)
class TickOutcome:
    """What happened to one tick in one sweep, from this worker's point of view.

    ``claimed`` being false is the ordinary result of losing a race, not an error: the
    other worker is doing the work, and this one moves on.
    """

    tick: ScheduleTick
    claimed: bool
    run: RadarRun | None = None
    settled: bool = True

    @property
    def executed(self) -> bool:
        return self.claimed and self.run is not None

    @property
    def succeeded(self) -> bool:
        return self.run is not None and self.run.status == RUN_SUCCEEDED


@dataclass(frozen=True)
class SweepResult:
    """One pass of plan-then-execute."""

    worker_id: str
    planned: tuple[PlanningResult, ...]
    outcomes: tuple[TickOutcome, ...]

    @property
    def executed(self) -> tuple[TickOutcome, ...]:
        return tuple(o for o in self.outcomes if o.executed)

    @property
    def runs(self) -> tuple[RadarRun, ...]:
        return tuple(o.run for o in self.outcomes if o.run is not None)


class ScheduledRadarOrchestrator:
    """Claims due ticks and drives them through the existing run/alerting path."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        application: CloudApplication,
        *,
        scheduler: RadarScheduler | None = None,
        worker_id: str = "worker-1",
        clock: Clock = utc_now,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not worker_id:
            raise ValueError("an orchestrator needs a worker id to hold leases with")
        self.uow_factory = uow_factory
        self.application = application
        self.scheduler = (
            scheduler if scheduler is not None else RadarScheduler(uow_factory, clock=clock)
        )
        self.worker_id = worker_id
        self.clock = clock
        self.batch_size = max(1, int(batch_size))

    # -------------------------------------------------------------------------- sweep

    def sweep(
        self,
        *,
        workspace_id: str | None = None,
        plan: bool = True,
        now: datetime | None = None,
    ) -> SweepResult:
        """Plan what is due, then execute what this worker manages to claim.

        Planning and execution are separate passes over separate transactions. Doing
        them together would mean holding a write lock across a radar execution, which
        is how one slow source becomes a stalled scheduler for every other tenant.
        """
        instant = now if now is not None else self.clock()
        planned: tuple[PlanningResult, ...] = ()
        if plan:
            planned = tuple(
                self.scheduler.plan_workspace(workspace_id, now=instant)
                if workspace_id is not None
                else self.scheduler.plan_all(now=instant)
            )

        outcomes: list[TickOutcome] = []
        for scope in self._scopes(workspace_id):
            for tick in self._claimable(scope, now=instant):
                outcomes.append(self.execute_tick(scope, tick.tick_id))
        return SweepResult(
            worker_id=self.worker_id,
            planned=planned,
            outcomes=tuple(outcomes),
        )

    def _scopes(self, workspace_id: str | None) -> list[str]:
        if workspace_id is not None:
            return [workspace_id]
        # Cross-tenant sweeps still execute one workspace at a time, so every claim,
        # read and settle below stays inside a single tenant's scope.
        with self.uow_factory() as uow:
            return sorted({s.workspace_id for s in uow.schedules.list_enabled_schedules()})

    def _claimable(self, workspace_id: str, *, now: datetime) -> Sequence[ScheduleTick]:
        with self.uow_factory() as uow:
            return uow.schedules.claimable_ticks(
                workspace_id,
                now=now.isoformat(),
                limit=self.batch_size,
            )

    # --------------------------------------------------------------------- one tick

    def execute_tick(self, workspace_id: str, tick_id: str) -> TickOutcome:
        """Claim one tick, run its radar as of its cutoff, and settle the result.

        The whole method is written so that dying at any point between the statements
        leaves recoverable state: before the claim there is a pending tick, after it a
        running tick whose lease will lapse, and after the run a radar run that a retry
        will recognise as already finished rather than repeat.
        """
        now = self.clock()
        claimed, tick, schedule = self._claim(workspace_id, tick_id, now=now)
        if not claimed or tick is None or schedule is None:
            stored = tick if tick is not None else self._load_tick(workspace_id, tick_id)
            return TickOutcome(tick=stored, claimed=False)

        if not schedule.enabled:
            # Disabled between planning and claiming. The tick is settled as skipped
            # rather than executed: a paused schedule that still fires is not paused.
            settled = tick.skipped(reason=SKIP_SCHEDULE_DISABLED, now=self.clock())
            persisted = self._settle(settled, expected_owner=self.worker_id)
            return TickOutcome(tick=settled, claimed=True, run=None, settled=persisted)

        try:
            run = self.application.run_radar(
                workspace_id=workspace_id,
                radar_id=tick.radar_id,
                evaluation_cutoff=tick.evaluation_cutoff,
            )
        except Exception as exc:
            code, detail = safe_error(exc)
            failed = tick.failed(code=code, detail=detail, now=self.clock())
            self._settle(failed, expected_owner=self.worker_id)
            return TickOutcome(tick=failed, claimed=True, run=None, settled=True)

        # The run is the authority on what happened, so the tick restates its verdict
        # rather than forming one. A degraded-coverage run succeeded: partial coverage
        # is a property of the evidence, not a scheduling failure, and recording it as
        # one would make a retry of it look justified.
        if run.status == RUN_SUCCEEDED:
            settled = tick.succeeded(run_id=run.run_id, now=self.clock())
        else:
            settled = tick.failed(
                code=run.error_code or "RunNotSucceeded",
                detail=run.error_detail or f"radar run ended {run.status}",
                now=self.clock(),
                run_id=run.run_id,
            )
        persisted = self._settle(settled, expected_owner=self.worker_id)
        return TickOutcome(tick=settled, claimed=True, run=run, settled=persisted)

    def _claim(
        self, workspace_id: str, tick_id: str, *, now: datetime
    ) -> tuple[bool, ScheduleTick | None, RadarSchedule | None]:
        with self.uow_factory() as uow:
            stored = uow.schedules.get_tick(workspace_id, tick_id)
            if stored is None:
                raise NotFoundError("schedule tick not found in workspace")
            schedule = uow.schedules.get_schedule(workspace_id, stored.schedule_id)
            if schedule is None:
                raise NotFoundError("schedule tick has no schedule in this workspace")
            lease = timedelta(seconds=schedule.lease_seconds)
            won = uow.schedules.claim_tick(
                workspace_id,
                tick_id,
                owner=self.worker_id,
                now=now.isoformat(),
                lease_expires_at=(now + lease).isoformat(),
            )
            if not won:
                uow.rollback()
                return False, stored, schedule
            self._meter(uow, stored)
            uow.commit()
            # Re-derive the in-memory tick from the same transition the store applied,
            # so the object this worker carries agrees with the row it just wrote.
            return True, stored.claimed(owner=self.worker_id, now=now, lease=lease), schedule

    def _settle(self, tick: ScheduleTick, *, expected_owner: str) -> bool:
        with self.uow_factory() as uow:
            persisted = uow.schedules.settle_tick(tick, expected_owner=expected_owner)
            if persisted:
                uow.commit()
            else:
                # The lease moved on while this worker was executing. Its results are
                # already in the run, which is idempotent, so the only thing lost is
                # this worker's right to write the verdict -- which it no longer has.
                uow.rollback()
        return persisted

    def _load_tick(self, workspace_id: str, tick_id: str) -> ScheduleTick:
        with self.uow_factory() as uow:
            stored = uow.schedules.get_tick(workspace_id, tick_id)
        if stored is None:
            raise NotFoundError("schedule tick not found in workspace")
        return stored

    @staticmethod
    def _meter(uow: UnitOfWork, tick: ScheduleTick) -> None:
        """Count one scheduled execution, keyed by the tick rather than the attempt.

        Consistent with every other meter in this system: a retried tick is the same
        unit of scheduled work, so a flaky source cannot inflate what a tenant is shown
        as having consumed. The radar run meters itself separately, as it always has.
        """
        uow.usage.record(
            UsageEvent.create(
                workspace_id=tick.workspace_id,
                kind=USAGE_SCHEDULED_TICK,
                quantity=1,
                occurred_at=tick.created_at,
                dedupe_key=entity_dedupe_key(USAGE_SCHEDULED_TICK, tick.tick_id),
            )
        )
