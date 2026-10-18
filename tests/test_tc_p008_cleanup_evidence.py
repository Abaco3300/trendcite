"""Fail-closed cleanup evidence contract (no DB connections)."""

import pytest

from trendcite.cloud.tc_p008_cleanup_evidence import verify_probe_cleanup

GOOD: dict[str, object] = {
    "target_isolated": True,
    "cleanup_targeted": True,
    "independent_readback": True,
    "sessions_closed": True,
    "probe_run": "run-unique",
    "probe_key": "key-unique",
    "remaining_rows": 0,
}


def test_valid_shape_never_claims_hosted_pass() -> None:
    assert verify_probe_cleanup(GOOD) == {
        "cleanup_contract": "PASS",
        "hosted_cleanup": "NOT_VERIFIED",
    }


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("target_isolated", False),
        ("cleanup_targeted", False),
        ("independent_readback", False),
        ("sessions_closed", False),
        ("probe_run", ""),
        ("probe_key", None),
        ("remaining_rows", 1),
        ("remaining_rows", False),
        ("remaining_rows", "0"),
    ],
)
def test_incomplete_cleanup_fails_closed(field: str, bad_value: object) -> None:
    evidence = dict(GOOD)
    evidence[field] = bad_value
    with pytest.raises(RuntimeError, match="cleanup unverified"):
        verify_probe_cleanup(evidence)
