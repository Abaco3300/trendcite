"""Reject synthetic or incomplete hosted-B proof without certifying claims."""

from copy import deepcopy

import pytest
from scripts.tc_p008_test_b_evidence_gate import assess_evidence

GOOD = {
    "worker": "trendcite-tcp008-fault-worker",
    "database_id": "bb27daa5-3f9e-488d-aa55-27c62a6dd325",
    "run_id": "123e4567-e89b-42d3-a456-426614174000",
    "provider_event": {
        "source": "cloudflare_workers_trace",
        "worker": "trendcite-tcp008-fault-worker",
        "run_id": "123e4567-e89b-42d3-a456-426614174000",
        "outcome": "exceededCpu",
        "timestamp": "2026-10-22T12:00:00Z",
        "event_id": "trace-1",
    },
    "d1_readback": {
        "source": "cloudflare_d1_independent_query",
        "run_id": "123e4567-e89b-42d3-a456-426614174000",
        "row_count": 1,
        "phase": "committed",
        "timestamp": "2026-10-22T12:01:00Z",
    },
}


def test_complete_claim_never_self_certifies() -> None:
    result = assess_evidence(GOOD)
    assert result["status"] == "EVIDENCE_COMPLETE_PENDING_INDEPENDENT_AUTHENTICATION"
    assert result["hosted_certification"] == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "section,field,bad",
    [
        ("provider_event", "source", "test_fixture"),
        ("provider_event", "outcome", "exception"),
        ("provider_event", "run_id", "another-run"),
        ("provider_event", "timestamp", "2026-10-22T12:02:00Z"),
        ("provider_event", "event_id", ""),
        ("d1_readback", "row_count", 0),
        ("d1_readback", "row_count", True),
        ("d1_readback", "source", "worker_self_report"),
        ("d1_readback", "phase", "pending"),
    ],
)
def test_missing_or_inconsistent_evidence_fails_closed(section, field, bad) -> None:
    value = deepcopy(GOOD)
    value[section][field] = bad
    assert assess_evidence(value)["status"] == "NOT_VERIFIED"


def test_empty_and_forged_targets_rejected() -> None:
    assert assess_evidence({})["status"] == "NOT_VERIFIED"
    value = deepcopy(GOOD)
    value["database_id"] = "shared-production"
    assert assess_evidence(value)["status"] == "NOT_VERIFIED"
