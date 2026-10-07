from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trendcite.cloud.domain.entitlements import (
    CAP_RADAR_RUN,
    NONPROD_PLAN_DEFINITIONS,
    PLAN_NONPROD_FULL,
    PLAN_NONPROD_LIMITED,
    monthly_period,
)
from trendcite.cloud.errors import ValidationError


def test_monthly_period_uses_utc_calendar_month() -> None:
    start, end = monthly_period(datetime(2026, 10, 7, 14, 30, tzinfo=UTC))
    assert start == datetime(2026, 10, 1, tzinfo=UTC)
    assert end == datetime(2026, 11, 1, tzinfo=UTC)


def test_monthly_period_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        monthly_period(datetime(2026, 10, 7, 14, 30))


def test_nonprod_plans_are_noncommercial_capability_definitions() -> None:
    limited = NONPROD_PLAN_DEFINITIONS[PLAN_NONPROD_LIMITED]
    full = NONPROD_PLAN_DEFINITIONS[PLAN_NONPROD_FULL]
    assert limited["capabilities"][CAP_RADAR_RUN] is True
    assert limited["quotas"][CAP_RADAR_RUN]["limit"] == 10
    assert full["capabilities"][CAP_RADAR_RUN] is True
    assert full["quotas"] == {}
