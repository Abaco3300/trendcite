"""Offline acceptance tests for linked contention and cleanup evidence."""

import pytest

from trendcite.cloud.tc_p008_hosted_evidence_gate import assess_hosted_probe

CONTENTION: dict[str, object] = {
    "holder_pid": 101,
    "contender_pid": 102,
    "blocking_pid": 101,
    "blocked_pid": 102,
    "holder_commit": True,
    "contender_insert_count": 0,
    "durable_count": 1,
    "winner": "holder",
    "cleanup_count": 0,
    "isolated_nonprod": True,
    "probe_key": "key-a",
    "probe_run": "run-a",
}
CLEANUP: dict[str, object] = {
    "target_isolated": True,
    "cleanup_targeted": True,
    "independent_readback": True,
    "sessions_closed": True,
    "probe_key": "key-a",
    "probe_run": "run-a",
    "remaining_rows": 0,
}


def test_explicit_attestation_and_linked_evidence_required() -> None:
    assert assess_hosted_probe(CONTENTION, CLEANUP, hosted_run_attested=True) == {
        "evidence_contract": "PASS",
        "hosted_result": "REQUIRES_INDEPENDENT_REVIEW",
    }


def test_no_attestation_fails_closed() -> None:
    with pytest.raises(RuntimeError, match="attestation"):
        assess_hosted_probe(CONTENTION, CLEANUP)


@pytest.mark.parametrize(
    ("category", "key", "value"),
    [
        ("contention", "holder_pid", 102),
        ("contention", "blocking_pid", 999),
        ("contention", "durable_count", 2),
        ("contention", "holder_commit", False),
        ("cleanup", "remaining_rows", 1),
        ("cleanup", "sessions_closed", False),
        ("cleanup", "probe_key", "key-b"),
        ("cleanup", "probe_run", "run-b"),
    ],
)
def test_invalid_evidence_rejected(category: str, key: str, value: object) -> None:
    c, k = dict(CONTENTION), dict(CLEANUP)
    (c if category == "contention" else k)[key] = value
    with pytest.raises(RuntimeError):
        assess_hosted_probe(c, k, hosted_run_attested=True)
