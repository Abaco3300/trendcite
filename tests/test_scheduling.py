"""The scheduling domain: cadence grids, due-work planning and tick transitions.

Everything here is pure -- no database, no clock, no I/O -- because that is the claim
the module makes. If a boundary needed a database to be decided, "the same cutoff
resolves to the same run" would be a property of a particular deployment rather than
of the algorithm.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trendcite.cloud.domain.scheduling import (
    CADENCE_DAILY,
    CADENCE_HOURLY,
    CADENCE_SIX_HOURLY,
    CADENCE_WEEKLY,
    MAX_PLAN_BOUNDARIES,
    SKIP_CATCH_UP_EXCEEDED,
    TICK_FAILED,
    TICK_PENDING,
    TICK_RUNNING,
    TICK_SKIPPED,
    TICK_SUCCEEDED,
    RadarSchedule,
    ScheduleTick,
    plan_due,
)
from trendcite.cloud.errors import ValidationError
from trendcite.cloud.ids import radar_schedule_id, schedule_tick_idempotency_key

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
WORKSPACE = "workspace-a"
RADAR = "radar-a"


def schedule(
    *,
    cadence: str = CADENCE_HOURLY,
    effective_from: datetime = NOW,
    enabled: bool = True,
    utc_offset_minutes: int = 0,
    at_hour: int = 0,
    at_minute: int = 0,
    weekday: int = 0,
    max_catch_up: int = 3,
    max_attempts: int = 3,
    lease_seconds: int = 300,
    workspace_id: str = WORKSPACE,
    radar_id: str = RADAR,
) -> RadarSchedule:
    return RadarSchedule.create(
        workspace_id=workspace_id,
        radar_id=radar_id,
        cadence=cadence,
        effective_from=effective_from,
        enabled=enabled,
        utc_offset_minutes=utc_offset_minutes,
        at_hour=at_hour,
        at_minute=at_minute,
        weekday=weekday,
        max_catch_up=max_catch_up,
        max_attempts=max_attempts,
        lease_seconds=lease_seconds,
        created_at=NOW,
    )


# ------------------------------------------------------------------------- identity


def test_schedule_identity_is_workspace_and_radar_scoped() -> None:
    first = schedule()
    second = schedule(cadence=CADENCE_DAILY, at_hour=9)
    other_radar = schedule(radar_id="radar-b")
    other_workspace = schedule(workspace_id="workspace-b")

    # Re-configuring a radar edits its one schedule; it does not create a second.
    assert first.schedule_id == second.schedule_id
    assert first.schedule_id == radar_schedule_id(WORKSPACE, RADAR)
    assert first.schedule_id != other_radar.schedule_id
    assert first.schedule_id != other_workspace.schedule_id


def test_schedule_rejects_unknown_cadence_and_out_of_range_fields() -> None:
    for kwargs in (
        {"cadence": "fortnightly"},
        {"at_hour": 24},
        {"at_minute": 60},
        {"weekday": 7},
        {"utc_offset_minutes": 900},
        {"max_catch_up": 51},
        {"max_attempts": 0},
    ):
        with pytest.raises(ValidationError):
            schedule(**kwargs)  # type: ignore[arg-type]


def test_schedule_refuses_naive_datetimes() -> None:
    with pytest.raises(ValidationError):
        schedule(effective_from=datetime(2026, 9, 22, 12, 0))


# -------------------------------------------------------------------- cadence grids


def test_hourly_anchor_is_the_next_boundary_at_or_after_effective_from() -> None:
    value = schedule(
        cadence=CADENCE_HOURLY,
        at_minute=30,
        effective_from=datetime(2026, 9, 22, 12, 31, tzinfo=UTC),
    )
    assert value.anchor_at == datetime(2026, 9, 22, 13, 30, tzinfo=UTC)
    assert value.next_boundary_after(value.anchor_at) == datetime(2026, 9, 22, 14, 30, tzinfo=UTC)


def test_daily_local_time_resolves_through_the_fixed_offset() -> None:
    # 09:00 at UTC-5 is 14:00Z. The tenant states local intent; the grid is UTC.
    value = schedule(
        cadence=CADENCE_DAILY,
        at_hour=9,
        utc_offset_minutes=-300,
        effective_from=datetime(2026, 9, 22, 0, 0, tzinfo=UTC),
    )
    assert value.anchor_at == datetime(2026, 9, 22, 14, 0, tzinfo=UTC)
    assert value.local(value.anchor_at).hour == 9


def test_six_hourly_time_of_day_is_a_phase_within_the_period() -> None:
    value = schedule(
        cadence=CADENCE_SIX_HOURLY,
        at_hour=2,
        effective_from=datetime(2026, 9, 22, 0, 0, tzinfo=UTC),
    )
    boundaries = tuple(value.boundaries_between(None, datetime(2026, 9, 22, 23, 59, tzinfo=UTC)))
    assert boundaries == (
        datetime(2026, 9, 22, 2, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 14, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 20, 0, tzinfo=UTC),
    )


def test_weekly_lands_on_the_requested_weekday() -> None:
    # 2026-09-22 is a Tuesday; weekday=4 is Friday.
    value = schedule(cadence=CADENCE_WEEKLY, weekday=4, at_hour=8)
    assert value.anchor_at == datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
    assert value.anchor_at.weekday() == 4
    assert value.next_boundary_after(value.anchor_at) == datetime(2026, 10, 2, 8, 0, tzinfo=UTC)


def test_boundary_lookup_is_deterministic_regardless_of_when_it_is_asked() -> None:
    """The whole point of a grid: asking late does not move the answer."""
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW)
    expected = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)
    for seconds in (0, 3, 47, 1799, 3599):
        asked = expected + timedelta(seconds=seconds)
        assert value.boundary_at_or_before(asked) == expected


def test_no_boundary_exists_before_the_anchor() -> None:
    value = schedule(effective_from=NOW)
    assert value.boundary_at_or_before(NOW - timedelta(days=1)) is None
    assert value.next_boundary_after(NOW - timedelta(days=1)) == value.anchor_at


# ------------------------------------------------------------------------- planning


def test_schedule_creates_deterministic_due_boundaries() -> None:
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, max_catch_up=10)
    plan = plan_due(value, now=NOW + timedelta(hours=3))
    assert plan.due == (
        datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 13, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 14, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 15, 0, tzinfo=UTC),
    )
    # Re-planning the same instant is the same answer, not more work.
    assert plan_due(value, now=NOW + timedelta(hours=3)).due == plan.due


def test_planning_from_a_watermark_never_re_yields_it() -> None:
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, max_catch_up=10)
    first = plan_due(value, now=NOW + timedelta(hours=2))
    assert first.watermark is not None
    advanced = value.planned_through(first.watermark)
    second = plan_due(advanced, now=NOW + timedelta(hours=2))
    assert second.due == ()
    third = plan_due(advanced, now=NOW + timedelta(hours=4))
    assert third.due == (
        datetime(2026, 9, 22, 15, 0, tzinfo=UTC),
        datetime(2026, 9, 22, 16, 0, tzinfo=UTC),
    )


def test_catch_up_is_bounded_and_keeps_the_newest_boundaries() -> None:
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, max_catch_up=3)
    # Twenty-four hours of missed boundaries; the budget is three.
    plan = plan_due(value, now=NOW + timedelta(hours=24))
    assert len(plan.due) == 3
    assert plan.due == (
        datetime(2026, 9, 23, 10, 0, tzinfo=UTC),
        datetime(2026, 9, 23, 11, 0, tzinfo=UTC),
        datetime(2026, 9, 23, 12, 0, tzinfo=UTC),
    )
    # The rest are reported as skipped rather than silently dropped.
    assert len(plan.skipped) == 22
    assert plan.watermark == datetime(2026, 9, 23, 12, 0, tzinfo=UTC)


def test_catch_up_of_zero_still_plans_the_boundaries_that_are_due() -> None:
    """Zero is "no cap", not "no work": the cap only decides how far back to reach."""
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, max_catch_up=0)
    plan = plan_due(value, now=NOW + timedelta(hours=2))
    assert len(plan.due) == 3
    assert plan.skipped == ()


def test_planning_is_bounded_even_when_a_schedule_is_not() -> None:
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, max_catch_up=50)
    boundaries = tuple(value.boundaries_between(None, NOW + timedelta(days=365)))
    assert len(boundaries) == MAX_PLAN_BOUNDARIES


def test_disabled_schedule_plans_nothing() -> None:
    value = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, enabled=False)
    plan = plan_due(value, now=NOW + timedelta(days=7))
    assert plan.due == ()
    assert plan.skipped == ()
    assert plan.watermark is None


def test_enabling_a_paused_schedule_resumes_within_the_catch_up_budget() -> None:
    paused = schedule(cadence=CADENCE_HOURLY, effective_from=NOW, enabled=False)
    assert plan_due(paused, now=NOW + timedelta(hours=10)).due == ()
    resumed = paused.with_enabled(True, updated_at=NOW + timedelta(hours=10))
    plan = plan_due(resumed, now=NOW + timedelta(hours=10))
    assert len(plan.due) == 3
    assert len(plan.skipped) == 8


def test_watermark_only_moves_forward() -> None:
    value = schedule(effective_from=NOW)
    ahead = value.planned_through(NOW + timedelta(hours=5))
    behind = ahead.planned_through(NOW + timedelta(hours=1))
    assert behind.last_planned_at == NOW + timedelta(hours=5)


# ----------------------------------------------------------------------------- ticks


def test_tick_identity_is_schedule_and_boundary() -> None:
    value = schedule()
    cutoff = datetime(2026, 9, 22, 13, 0, tzinfo=UTC)
    first = ScheduleTick.create(schedule=value, evaluation_cutoff=cutoff, created_at=NOW)
    later = ScheduleTick.create(
        schedule=value, evaluation_cutoff=cutoff, created_at=NOW + timedelta(hours=9)
    )
    other = ScheduleTick.create(
        schedule=value,
        evaluation_cutoff=cutoff + timedelta(hours=1),
        created_at=NOW,
    )
    # When it was planned is not part of what it is.
    assert first.tick_id == later.tick_id
    assert first.idempotency_key == schedule_tick_idempotency_key(
        value.schedule_id, cutoff.isoformat()
    )
    assert first.tick_id != other.tick_id


def test_tick_starts_pending_with_no_attempts_and_no_lease() -> None:
    value = schedule()
    tick = ScheduleTick.create(schedule=value, evaluation_cutoff=NOW, created_at=NOW)
    assert tick.status == TICK_PENDING
    assert tick.attempt == 0
    assert tick.lease_owner == ""
    assert tick.lease_expires_at is None
    assert tick.claimable_at(NOW)
    assert not tick.finished


def test_claiming_takes_the_lease_and_counts_the_attempt() -> None:
    tick = ScheduleTick.create(schedule=schedule(), evaluation_cutoff=NOW, created_at=NOW)
    claimed = tick.claimed(owner="worker-1", now=NOW, lease=timedelta(minutes=5))
    assert claimed.status == TICK_RUNNING
    assert claimed.attempt == 1
    assert claimed.lease_owner == "worker-1"
    assert claimed.lease_expires_at == NOW + timedelta(minutes=5)
    assert claimed.lease_held_at(NOW + timedelta(minutes=4))
    assert not claimed.lease_held_at(NOW + timedelta(minutes=6))


def test_a_held_lease_blocks_another_worker_and_an_expired_one_does_not() -> None:
    tick = ScheduleTick.create(schedule=schedule(), evaluation_cutoff=NOW, created_at=NOW)
    held = tick.claimed(owner="worker-1", now=NOW, lease=timedelta(minutes=5))

    assert not held.claimable_at(NOW + timedelta(minutes=1))
    with pytest.raises(ValidationError):
        held.claimed(owner="worker-2", now=NOW + timedelta(minutes=1), lease=timedelta(minutes=5))

    expired_at = NOW + timedelta(minutes=6)
    assert held.claimable_at(expired_at)
    reclaimed = held.claimed(owner="worker-2", now=expired_at, lease=timedelta(minutes=5))
    assert reclaimed.lease_owner == "worker-2"
    assert reclaimed.attempt == 2


def test_a_succeeded_tick_can_never_be_claimed_again() -> None:
    tick = ScheduleTick.create(schedule=schedule(), evaluation_cutoff=NOW, created_at=NOW)
    done = tick.claimed(owner="w", now=NOW, lease=timedelta(minutes=5)).succeeded(
        run_id="run-1", now=NOW + timedelta(minutes=1)
    )
    assert done.status == TICK_SUCCEEDED
    assert done.finished
    assert not done.claimable_at(NOW + timedelta(days=30))
    with pytest.raises(ValidationError):
        done.claimed(owner="w2", now=NOW + timedelta(days=30), lease=timedelta(minutes=5))


def test_a_failed_tick_retries_until_its_budget_is_spent() -> None:
    value = schedule(max_attempts=2)
    tick = ScheduleTick.create(schedule=value, evaluation_cutoff=NOW, created_at=NOW)

    first = tick.claimed(owner="w", now=NOW, lease=timedelta(minutes=5)).failed(
        code="RuntimeError", detail="source refused", now=NOW + timedelta(minutes=1)
    )
    assert first.status == TICK_FAILED
    assert first.attempt == 1
    assert first.retryable
    assert not first.finished
    # A settled failure releases the lease: a retry should not wait out a timeout for
    # work that is demonstrably no longer in flight.
    assert first.lease_owner == ""

    second = first.claimed(
        owner="w", now=NOW + timedelta(minutes=2), lease=timedelta(minutes=5)
    ).failed(code="RuntimeError", detail="again", now=NOW + timedelta(minutes=3))
    assert second.attempt == 2
    assert not second.retryable
    assert second.finished
    assert not second.claimable_at(NOW + timedelta(days=1))
    with pytest.raises(ValidationError):
        second.claimed(owner="w", now=NOW + timedelta(days=1), lease=timedelta(minutes=5))


def test_failure_detail_is_bounded_and_the_code_is_kept() -> None:
    tick = ScheduleTick.create(schedule=schedule(), evaluation_cutoff=NOW, created_at=NOW)
    failed = tick.claimed(owner="w", now=NOW, lease=timedelta(minutes=5)).failed(
        code="X" * 200, detail="y " * 500, now=NOW
    )
    assert len(failed.error_code) == 80
    assert len(failed.error_detail) <= 200


def test_a_skipped_tick_is_born_finished() -> None:
    tick = ScheduleTick.create(
        schedule=schedule(),
        evaluation_cutoff=NOW,
        created_at=NOW,
        status=TICK_SKIPPED,
        skip_reason=SKIP_CATCH_UP_EXCEEDED,
    )
    assert tick.status == TICK_SKIPPED
    assert tick.finished
    assert not tick.claimable_at(NOW)
    assert tick.finished_at == NOW


def test_a_tick_cannot_be_born_running_or_skipped_without_a_reason() -> None:
    value = schedule()
    with pytest.raises(ValidationError):
        ScheduleTick.create(
            schedule=value, evaluation_cutoff=NOW, created_at=NOW, status=TICK_RUNNING
        )
    with pytest.raises(ValidationError):
        ScheduleTick.create(
            schedule=value, evaluation_cutoff=NOW, created_at=NOW, status=TICK_SKIPPED
        )


def test_tick_and_schedule_round_trip_through_dicts() -> None:
    value = schedule()
    tick = ScheduleTick.create(schedule=value, evaluation_cutoff=NOW, created_at=NOW)
    assert value.to_dict()["cadence"] == CADENCE_HOURLY
    assert tick.to_dict()["evaluation_cutoff"] == NOW.isoformat()
    assert tick.to_dict()["lease_expires_at"] is None
