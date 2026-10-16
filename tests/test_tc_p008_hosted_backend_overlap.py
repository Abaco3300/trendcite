from datetime import UTC, datetime, timedelta

import pytest
from scripts.tc_p008_hosted_backend_overlap import validate_backend_samples


def pair(*, overlap: bool, same_pid: bool = False):
    now = datetime(2026, 10, 16, tzinfo=UTC)
    first = {"pid": 11, "start": now, "end": now + timedelta(seconds=2)}
    second_start = now + timedelta(seconds=1 if overlap else 3)
    second = {
        "pid": 11 if same_pid else 12,
        "start": second_start,
        "end": second_start + timedelta(seconds=2),
    }
    return first, second


def test_overlapping_distinct_backends() -> None:
    assert validate_backend_samples(*pair(overlap=True))["overlap"] is True


def test_sequential_backends_rejected() -> None:
    with pytest.raises(RuntimeError, match="do not overlap"):
        validate_backend_samples(*pair(overlap=False))


def test_reused_backend_rejected() -> None:
    with pytest.raises(RuntimeError, match="independent"):
        validate_backend_samples(*pair(overlap=True, same_pid=True))
