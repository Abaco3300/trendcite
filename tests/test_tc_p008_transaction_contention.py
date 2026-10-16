import pytest

from trendcite.cloud.tc_p008_transaction_contention import validate_transaction_observations


def test_real_distinct_transaction_lock_conflict_classifies() -> None:
    result = validate_transaction_observations(
        {"holder_pid": 101, "contender_pid": 102, "blocked": True}
    )
    assert result["concurrent_transaction_lock_contention"] is True
    assert result["unique_key_write_contention"] == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "evidence",
    [
        {"holder_pid": 101, "contender_pid": 101, "blocked": True},
        {"holder_pid": 101, "contender_pid": 102, "blocked": False},
        {"holder_pid": 0, "contender_pid": 102, "blocked": True},
        {"holder_pid": 101, "contender_pid": None, "blocked": True},
        {},
    ],
)
def test_missing_or_ambiguous_contention_fails_closed(evidence: dict) -> None:
    with pytest.raises(RuntimeError, match="not established"):
        validate_transaction_observations(evidence)
