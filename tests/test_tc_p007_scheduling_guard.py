from datetime import UTC, datetime, timedelta

import pytest

from trendcite.cloud.domain.scheduling import CADENCE_HOURLY, RadarSchedule, ScheduleTick
from trendcite.cloud.errors import ValidationError

NOW = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)


def test_expired_lease_on_final_attempt_is_not_claimable() -> None:
    schedule = RadarSchedule.create(
        workspace_id="ws-a",
        radar_id="radar-a",
        cadence=CADENCE_HOURLY,
        effective_from=NOW,
        max_attempts=1,
        created_at=NOW,
    )
    tick = ScheduleTick.create(
        schedule=schedule,
        evaluation_cutoff=NOW,
        created_at=NOW,
    )
    running = tick.claimed(
        owner="worker-1",
        now=NOW,
        lease=timedelta(minutes=1),
    )
    expired = NOW + timedelta(minutes=2)
    assert running.attempt == 1
    assert not running.lease_held_at(expired)
    assert not running.claimable_at(expired)
    with pytest.raises(ValidationError):
        running.claimed(
            owner="worker-2",
            now=expired,
            lease=timedelta(minutes=1),
        )
