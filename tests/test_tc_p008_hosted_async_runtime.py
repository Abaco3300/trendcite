"""TC-P008: fail-closed classification by the deployed hosted runtime module."""

from datetime import UTC, datetime, timedelta

import pytest

from trendcite.cloud.tc_p008_hosted_backend_overlap import validate_backend_samples


def sample_pair():
    now = datetime(2026, 10, 16, tzinfo=UTC)
    return (
        {"pid": 101, "start": now, "end": now + timedelta(seconds=2)},
        {"pid": 102, "start": now + timedelta(seconds=1), "end": now + timedelta(seconds=3)},
    )


def test_runtime_accepts_distinct_overlapping_postgres_backends() -> None:
    result = validate_backend_samples(*sample_pair())
    assert result["backends_distinct"] is True
    assert result["overlap"] is True
    assert result["worker_termination"] == "NOT_VERIFIED"
    assert result["transport_ack_loss"] == "NOT_VERIFIED"


@pytest.mark.parametrize("defect", ["same_pid", "sequential", "naive", "reverse", "zero_pid"])
def test_runtime_rejects_invalid_backend_evidence(defect: str) -> None:
    a, b = sample_pair()
    if defect == "same_pid":
        b["pid"] = a["pid"]
    elif defect == "sequential":
        b["start"] = a["end"] + timedelta(seconds=1)
        b["end"] = b["start"] + timedelta(seconds=1)
    elif defect == "naive":
        b["start"] = b["start"].replace(tzinfo=None)
    elif defect == "reverse":
        b["end"] = b["start"]
    elif defect == "zero_pid":
        a["pid"] = 0
    with pytest.raises(RuntimeError):
        validate_backend_samples(a, b)
