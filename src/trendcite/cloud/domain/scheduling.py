"""RadarSchedule and ScheduleTick: when a radar should run, and what happened when it did.

Three separations are load-bearing here, and each of them is enforced by construction
rather than by convention:

**Scheduling is not execution.** A :class:`RadarSchedule` decides *when*; it never
knows what a source is, what a match is or what a delivery is. A :class:`ScheduleTick`
is the record of one decision to execute, and it points at a ``RadarRun`` rather than
restating one. Two schedules aimed at the same radar and the same boundary produce two
ticks and *one* run, because the run's identity is (workspace, radar version, cutoff)
and is none of the scheduler's business.

**A boundary is a canonical instant, not "roughly now".** The cadence grid is a pure
function of (cadence, fixed UTC offset, local time-of-day, effective_from). Planning at
09:00:03 and re-planning at 09:47:11 both yield the 09:00:00 boundary, so the same
cutoff resolves to the same logical run however late or however often the planner ran.
That is what makes a scheduler safe to invoke twice.

**A lease is not a status.** ``status`` says what has happened to the work; the lease
says who is currently allowed to touch it. Keeping them apart is what lets an
interrupted worker's tick be reclaimed without inventing a "probably dead" status, and
what lets a stale worker's late settlement be refused by owner rather than by guesswork.

Timezones are fixed UTC offsets, deliberately. An IANA zone would need the system tz
database (absent on many Windows installs without an extra package), and, worse, a DST
transition makes "daily at 02:30 local" either ambiguous or non-existent twice a year
-- which would make the cutoff, and therefore the run identity, undefined on exactly
those days. A fixed offset keeps every boundary a single unambiguous instant. A tenant
who observes DST is served by editing the offset, which is an ordinary schedule edit
and moves only *future* boundaries.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from .. import ids
from ..errors import ValidationError
from ..versions import SCHEDULE_CADENCE_VERSION
from ._base import iso, require_aware

# ----------------------------------------------------------------------------- cadence

CADENCE_HOURLY = "hourly"
CADENCE_SIX_HOURLY = "six_hourly"
CADENCE_TWELVE_HOURLY = "twelve_hourly"
CADENCE_DAILY = "daily"
CADENCE_WEEKLY = "weekly"

#: Every supported cadence, and the exact length of its period. A cadence is a named
#: period rather than a free-form interval on purpose: "every 37 minutes" has no
#: canonical local alignment, and a grid nobody can predict is a grid nobody can audit.
CADENCE_MINUTES: dict[str, int] = {
    CADENCE_HOURLY: 60,
    CADENCE_SIX_HOURLY: 6 * 60,
    CADENCE_TWELVE_HOURLY: 12 * 60,
    CADENCE_DAILY: 24 * 60,
    CADENCE_WEEKLY: 7 * 24 * 60,
}
CADENCES = tuple(CADENCE_MINUTES)

#: Offsets outside one day are not a timezone, they are a typo.
MAX_UTC_OFFSET_MINUTES = 14 * 60
MIN_UTC_OFFSET_MINUTES = -12 * 60

#: How many missed boundaries a schedule will recover at most. The point of the cap is
#: that a radar switched off for a month must not wake up and execute 720 times; it
#: executes the most recent few and says how many it passed over.
DEFAULT_MAX_CATCH_UP = 3
MAX_CATCH_UP_LIMIT = 50

#: How long a claim is held before another worker may take the tick.
DEFAULT_LEASE_SECONDS = 300
#: How many times a tick may be executed before it is left failed for good.
DEFAULT_MAX_ATTEMPTS = 3
MAX_ATTEMPTS_LIMIT = 10

#: Hard ceiling on one planning pass, independent of any schedule's catch-up budget.
#: Belt and braces: the planner must be bounded even if a stored schedule is not.
MAX_PLAN_BOUNDARIES = 1000

# ------------------------------------------------------------------------ tick status

TICK_PENDING = "pending"
TICK_RUNNING = "running"
TICK_SUCCEEDED = "succeeded"
TICK_FAILED = "failed"
TICK_SKIPPED = "skipped"
TICK_STATUSES = (TICK_PENDING, TICK_RUNNING, TICK_SUCCEEDED, TICK_FAILED, TICK_SKIPPED)

#: Work that will never be done again. ``failed`` is absent on purpose: whether a
#: failed tick is finished depends on its attempt budget, which is a policy question
#: rather than a status one (see :attr:`ScheduleTick.retryable`).
TICK_TERMINAL_STATUSES = frozenset({TICK_SUCCEEDED, TICK_SKIPPED})

#: Why a tick was skipped rather than executed.
SKIP_CATCH_UP_EXCEEDED = "catch_up_exceeded"
SKIP_SCHEDULE_DISABLED = "schedule_disabled"
SKIP_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
SKIP_REASONS = (SKIP_CATCH_UP_EXCEEDED, SKIP_SCHEDULE_DISABLED, SKIP_ATTEMPTS_EXHAUSTED)

_MAX_DETAIL = 200


def _require_range(value: int, low: int, high: int, field: str) -> int:
    if not low <= value <= high:
        raise ValidationError(f"{field} must be between {low} and {high}")
    return value


@dataclass(frozen=True)
class RadarSchedule:
    """When one radar should run, stated as a canonical grid of instants.

    ``anchor_at`` is the first boundary the schedule will ever produce, already
    resolved to UTC. Everything after it is ``anchor_at + k * period``. Storing the
    resolved anchor rather than re-deriving it from wall-clock fields on every read is
    what makes the grid stable across an offset edit: editing the offset recomputes the
    anchor once, deliberately, instead of silently shifting every historical boundary.
    """

    schedule_id: str
    workspace_id: str
    radar_id: str
    enabled: bool
    cadence: str
    utc_offset_minutes: int
    anchor_at: datetime
    max_catch_up: int
    lease_seconds: int
    max_attempts: int
    cadence_version: str
    created_at: datetime
    updated_at: datetime
    last_planned_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        workspace_id: str,
        radar_id: str,
        cadence: str,
        effective_from: datetime,
        enabled: bool = True,
        utc_offset_minutes: int = 0,
        at_hour: int = 0,
        at_minute: int = 0,
        weekday: int = 0,
        max_catch_up: int = DEFAULT_MAX_CATCH_UP,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        created_at: datetime,
    ) -> RadarSchedule:
        """Resolve wall-clock intent into a canonical UTC grid.

        ``at_hour``/``at_minute``/``weekday`` are read in the schedule's own offset, so
        "daily at 09:00, offset -300" means 14:00Z -- which is what the tenant asked
        for, stated in the one form the rest of the system can compare.
        """
        if cadence not in CADENCE_MINUTES:
            raise ValidationError(f"cadence must be one of {', '.join(CADENCES)}")
        offset = _require_range(
            int(utc_offset_minutes),
            MIN_UTC_OFFSET_MINUTES,
            MAX_UTC_OFFSET_MINUTES,
            "utc_offset_minutes",
        )
        _require_range(int(at_hour), 0, 23, "at_hour")
        _require_range(int(at_minute), 0, 59, "at_minute")
        _require_range(int(weekday), 0, 6, "weekday")
        anchor = _first_boundary(
            cadence=cadence,
            effective_from=require_aware(effective_from, "effective_from"),
            utc_offset_minutes=offset,
            at_hour=int(at_hour),
            at_minute=int(at_minute),
            weekday=int(weekday),
        )
        now = require_aware(created_at, "created_at")
        return cls(
            schedule_id=ids.radar_schedule_id(workspace_id, radar_id),
            workspace_id=workspace_id,
            radar_id=radar_id,
            enabled=bool(enabled),
            cadence=cadence,
            utc_offset_minutes=offset,
            anchor_at=anchor,
            max_catch_up=_require_range(int(max_catch_up), 0, MAX_CATCH_UP_LIMIT, "max_catch_up"),
            lease_seconds=_require_range(int(lease_seconds), 1, 86_400, "lease_seconds"),
            max_attempts=_require_range(int(max_attempts), 1, MAX_ATTEMPTS_LIMIT, "max_attempts"),
            cadence_version=SCHEDULE_CADENCE_VERSION,
            created_at=now,
            updated_at=now,
            last_planned_at=None,
        )

    # ----------------------------------------------------------------- cadence grid

    @property
    def period(self) -> timedelta:
        return timedelta(minutes=CADENCE_MINUTES[self.cadence])

    @property
    def lease(self) -> timedelta:
        return timedelta(seconds=self.lease_seconds)

    def local(self, moment: datetime) -> datetime:
        """The schedule's own wall-clock reading of an instant, for display only."""
        return require_aware(moment, "moment") + timedelta(minutes=self.utc_offset_minutes)

    def boundary_at_or_before(self, moment: datetime) -> datetime | None:
        """The most recent boundary at or before ``moment``, or None before the anchor."""
        instant = require_aware(moment, "moment")
        if instant < self.anchor_at:
            return None
        elapsed = instant - self.anchor_at
        periods = int(elapsed // self.period)
        return self.anchor_at + periods * self.period

    def next_boundary_after(self, moment: datetime) -> datetime:
        """The first boundary strictly after ``moment``."""
        instant = require_aware(moment, "moment")
        if instant < self.anchor_at:
            return self.anchor_at
        previous = self.anchor_at + int((instant - self.anchor_at) // self.period) * self.period
        return previous + self.period

    def boundaries_between(self, after: datetime | None, until: datetime) -> Iterator[datetime]:
        """Every boundary in ``(after, until]``, oldest first.

        Half-open at the lower end so that re-planning from the last boundary already
        planned yields the *next* one and never re-yields it, and closed at the upper
        end so that a boundary falling exactly on ``now`` is due now rather than in one
        more period.
        """
        end = require_aware(until, "until")
        current = self.anchor_at if after is None else self.next_boundary_after(after)
        emitted = 0
        while current <= end:
            yield current
            emitted += 1
            if emitted >= MAX_PLAN_BOUNDARIES:
                return
            current += self.period

    # -------------------------------------------------------------------- transitions

    def with_enabled(self, enabled: bool, *, updated_at: datetime) -> RadarSchedule:
        return replace(
            self,
            enabled=bool(enabled),
            updated_at=require_aware(updated_at, "updated_at"),
        )

    def planned_through(self, boundary: datetime) -> RadarSchedule:
        """Record the newest boundary this schedule has produced a tick for.

        Only ever moves forward. The watermark is an optimisation -- tick identity is
        what actually prevents duplicates -- so a stale or absent watermark costs a
        re-derivation, never a second tick.
        """
        moment = require_aware(boundary, "boundary")
        if self.last_planned_at is not None and moment <= self.last_planned_at:
            return self
        return replace(self, last_planned_at=moment)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "enabled": self.enabled,
            "cadence": self.cadence,
            "utc_offset_minutes": self.utc_offset_minutes,
            "anchor_at": iso(self.anchor_at),
            "max_catch_up": self.max_catch_up,
            "lease_seconds": self.lease_seconds,
            "max_attempts": self.max_attempts,
            "cadence_version": self.cadence_version,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "last_planned_at": (
                None if self.last_planned_at is None else iso(self.last_planned_at)
            ),
        }


def _first_boundary(
    *,
    cadence: str,
    effective_from: datetime,
    utc_offset_minutes: int,
    at_hour: int,
    at_minute: int,
    weekday: int,
) -> datetime:
    """The first boundary at or after ``effective_from``, computed in local wall time.

    Local arithmetic is done on a shifted *aware* datetime rather than on a naive one:
    the shift is a fixed offset, so adding it and taking it away again is exact, and
    nothing here ever has to guess what zone a naive value meant.
    """
    offset = timedelta(minutes=utc_offset_minutes)
    local = effective_from + offset
    period = timedelta(minutes=CADENCE_MINUTES[cadence])

    if cadence == CADENCE_HOURLY:
        candidate = local.replace(minute=at_minute, second=0, microsecond=0)
    else:
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        if cadence in (CADENCE_SIX_HOURLY, CADENCE_TWELVE_HOURLY):
            # The time-of-day is a phase within the period, so "every six hours at
            # 02:00" means 02:00, 08:00, 14:00, 20:00 local rather than only 02:00.
            hours_in_period = CADENCE_MINUTES[cadence] // 60
            candidate = midnight + timedelta(hours=at_hour % hours_in_period, minutes=at_minute)
        elif cadence == CADENCE_WEEKLY:
            days_ahead = (weekday - midnight.weekday()) % 7
            candidate = midnight + timedelta(days=days_ahead, hours=at_hour, minutes=at_minute)
        else:
            candidate = midnight + timedelta(hours=at_hour, minutes=at_minute)

    while candidate < local:
        candidate += period
    return candidate - offset


@dataclass(frozen=True)
class DuePlan:
    """What one planning pass concluded for one schedule.

    ``skipped`` is reported rather than silently dropped: "we did not run 41 of the
    intervals you missed" is a fact a tenant is entitled to, and a planner that quietly
    discards work is indistinguishable from one that lost it.
    """

    schedule_id: str
    workspace_id: str
    radar_id: str
    due: tuple[datetime, ...]
    skipped: tuple[datetime, ...]

    @property
    def watermark(self) -> datetime | None:
        """The newest boundary this plan accounts for, skipped ones included."""
        considered = self.due + self.skipped
        return max(considered) if considered else None


def plan_due(schedule: RadarSchedule, *, now: datetime) -> DuePlan:
    """Derive the exact boundaries a schedule owes work for, bounded by its catch-up.

    Pure: same schedule, same ``now``, same answer, with no reference to a clock, a
    database or anything already executed. Whether a boundary has *already* been
    executed is a question about stored ticks, and it is answered by tick identity when
    the plan is persisted -- not here, where it could only be answered by guessing.
    """
    instant = require_aware(now, "now")
    if not schedule.enabled:
        return DuePlan(
            schedule_id=schedule.schedule_id,
            workspace_id=schedule.workspace_id,
            radar_id=schedule.radar_id,
            due=(),
            skipped=(),
        )
    boundaries = tuple(schedule.boundaries_between(schedule.last_planned_at, instant))
    budget = schedule.max_catch_up
    due: tuple[datetime, ...]
    skipped: tuple[datetime, ...]
    if budget == 0 or len(boundaries) <= budget:
        due, skipped = boundaries, ()
    else:
        # Keep the *newest* boundaries. A radar that has been off for a month wants
        # today's picture, not the replay of a month of stale cutoffs it would then
        # have to alert on.
        due, skipped = boundaries[-budget:], boundaries[:-budget]
    return DuePlan(
        schedule_id=schedule.schedule_id,
        workspace_id=schedule.workspace_id,
        radar_id=schedule.radar_id,
        due=due,
        skipped=skipped,
    )


@dataclass(frozen=True)
class ScheduleTick:
    """One scheduled execution of one radar at one canonical boundary.

    The status/lease split matters here. ``status`` is the history of the work;
    ``lease_owner``/``lease_expires_at`` are a revocable right to be the one doing it.
    A successful tick can never be claimed again whatever the lease says, and an
    expired lease can always be taken whatever the previous owner believes.
    """

    tick_id: str
    schedule_id: str
    workspace_id: str
    radar_id: str
    evaluation_cutoff: datetime
    idempotency_key: str
    status: str
    attempt: int
    max_attempts: int
    lease_owner: str
    lease_expires_at: datetime | None
    run_id: str
    skip_reason: str
    error_code: str
    error_detail: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def create(
        cls,
        *,
        schedule: RadarSchedule,
        evaluation_cutoff: datetime,
        created_at: datetime,
        status: str = TICK_PENDING,
        skip_reason: str = "",
    ) -> ScheduleTick:
        if status not in (TICK_PENDING, TICK_SKIPPED):
            raise ValidationError("a new tick starts pending, or is born skipped")
        if status == TICK_SKIPPED and skip_reason not in SKIP_REASONS:
            raise ValidationError(f"skip_reason must be one of {', '.join(SKIP_REASONS)}")
        cutoff = require_aware(evaluation_cutoff, "evaluation_cutoff")
        key = ids.schedule_tick_idempotency_key(schedule.schedule_id, iso(cutoff))
        now = require_aware(created_at, "created_at")
        return cls(
            tick_id=ids.schedule_tick_id(schedule.workspace_id, key),
            schedule_id=schedule.schedule_id,
            workspace_id=schedule.workspace_id,
            radar_id=schedule.radar_id,
            evaluation_cutoff=cutoff,
            idempotency_key=key,
            status=status,
            attempt=0,
            max_attempts=schedule.max_attempts,
            lease_owner="",
            lease_expires_at=None,
            run_id="",
            skip_reason=skip_reason,
            error_code="",
            error_detail="",
            created_at=now,
            updated_at=now,
            started_at=None,
            finished_at=now if status == TICK_SKIPPED else None,
        )

    # --------------------------------------------------------------------- predicates

    @property
    def finished(self) -> bool:
        """True when no further execution of this tick will ever happen."""
        if self.status in TICK_TERMINAL_STATUSES:
            return True
        return self.status == TICK_FAILED and self.attempt >= self.max_attempts

    @property
    def retryable(self) -> bool:
        """A failed tick with budget left. Not a status, because it is a policy verdict."""
        return self.status == TICK_FAILED and self.attempt < self.max_attempts

    def lease_held_at(self, moment: datetime) -> bool:
        """True when a live worker still owns this tick as of ``moment``."""
        if self.status != TICK_RUNNING or not self.lease_owner:
            return False
        if self.lease_expires_at is None:
            return False
        return require_aware(moment, "moment") < self.lease_expires_at

    def claimable_at(self, moment: datetime) -> bool:
        """Whether a worker could take this tick now, by the same rules the store uses.

        The authoritative check is the conditional UPDATE in the repository -- two
        workers asking this question simultaneously would both hear yes, and only one
        would win the write. This exists so a planner can avoid attempting claims it
        will certainly lose, not so anyone can skip the atomic one.
        """
        if self.status in TICK_TERMINAL_STATUSES:
            return False
        if self.status == TICK_PENDING:
            return True
        if self.status == TICK_FAILED:
            return self.retryable
        return not self.lease_held_at(moment)

    # -------------------------------------------------------------------- transitions

    def claimed(self, *, owner: str, now: datetime, lease: timedelta) -> ScheduleTick:
        """Take ownership as the next attempt. Refuses terminal work outright."""
        if not owner:
            raise ValidationError("a lease needs an owner")
        moment = require_aware(now, "now")
        if self.status in TICK_TERMINAL_STATUSES:
            raise ValidationError("a settled tick cannot be claimed")
        if self.status == TICK_FAILED and not self.retryable:
            raise ValidationError("a tick with no attempts left cannot be claimed")
        if self.lease_held_at(moment) and self.lease_owner != owner:
            raise ValidationError("another worker holds an unexpired lease on this tick")
        return replace(
            self,
            status=TICK_RUNNING,
            attempt=self.attempt + 1,
            lease_owner=owner,
            lease_expires_at=moment + lease,
            error_code="",
            error_detail="",
            updated_at=moment,
            started_at=moment,
            finished_at=None,
        )

    def succeeded(self, *, run_id: str, now: datetime) -> ScheduleTick:
        moment = require_aware(now, "now")
        return replace(
            self,
            status=TICK_SUCCEEDED,
            run_id=run_id,
            lease_owner="",
            lease_expires_at=None,
            error_code="",
            error_detail="",
            updated_at=moment,
            finished_at=moment,
        )

    def failed(self, *, code: str, detail: str, now: datetime, run_id: str = "") -> ScheduleTick:
        """Settle as failed, releasing the lease.

        The lease is dropped rather than held to expiry: the work is not in flight any
        more, and making a retry wait out a timeout after an *observed* failure would
        be delay bought with nothing.
        """
        moment = require_aware(now, "now")
        return replace(
            self,
            status=TICK_FAILED,
            run_id=run_id or self.run_id,
            lease_owner="",
            lease_expires_at=None,
            error_code=code[:80],
            error_detail=" ".join(detail.split())[:_MAX_DETAIL],
            updated_at=moment,
            finished_at=moment,
        )

    def skipped(self, *, reason: str, now: datetime) -> ScheduleTick:
        if reason not in SKIP_REASONS:
            raise ValidationError(f"skip_reason must be one of {', '.join(SKIP_REASONS)}")
        moment = require_aware(now, "now")
        return replace(
            self,
            status=TICK_SKIPPED,
            skip_reason=reason,
            lease_owner="",
            lease_expires_at=None,
            updated_at=moment,
            finished_at=moment,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_id": self.tick_id,
            "schedule_id": self.schedule_id,
            "workspace_id": self.workspace_id,
            "radar_id": self.radar_id,
            "evaluation_cutoff": iso(self.evaluation_cutoff),
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "lease_owner": self.lease_owner,
            "lease_expires_at": (
                None if self.lease_expires_at is None else iso(self.lease_expires_at)
            ),
            "run_id": self.run_id,
            "skip_reason": self.skip_reason,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "started_at": None if self.started_at is None else iso(self.started_at),
            "finished_at": None if self.finished_at is None else iso(self.finished_at),
        }
