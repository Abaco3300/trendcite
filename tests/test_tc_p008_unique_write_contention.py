"""Fail-closed tests for unique-key contention evidence."""

import pytest

from trendcite.cloud.tc_p008_unique_write_contention import validate_unique_write_contention


@pytest.fixture
def evidence() -> dict[str, object]:
    return {
        "holder_pid": 1001,
        "contender_pid": 1002,
        "blocking_pid": 1001,
        "blocked_pid": 1002,
        "holder_commit": True,
        "contender_insert_count": 0,
        "durable_count": 1,
        "winner": "holder",
        "cleanup_count": 0,
        "isolated_nonprod": True,
    }


def test_complete_contract_never_certifies_hosted(evidence: dict[str, object]) -> None:
    assert validate_unique_write_contention(evidence) == {
        "local_contract": "PASS",
        "hosted_unique_key_contention": "NOT_VERIFIED",
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("holder_pid", 0),
        ("holder_pid", 1002),
        ("holder_pid", True),
        ("contender_pid", None),
        ("blocking_pid", 9999),
        ("blocked_pid", None),
        ("holder_commit", False),
        ("contender_insert_count", 1),
        ("durable_count", 2),
        ("winner", "contender"),
        ("cleanup_count", 1),
        ("isolated_nonprod", False),
    ],
)
def test_incomplete_evidence_is_rejected(
    evidence: dict[str, object], key: str, value: object
) -> None:
    evidence[key] = value
    with pytest.raises(RuntimeError):
        validate_unique_write_contention(evidence)
