"""Failure precedence matrix: preserve primary errors and cleanup errors."""

import itertools

import pytest

from trendcite.cloud.tc_p008_failure_disposition import record_failure


@pytest.mark.parametrize(
    ("cleanup_failed", "sessions_active"),
    list(itertools.product((False, True), repeat=2)),
)
def test_primary_failure_is_never_hidden(cleanup_failed: bool, sessions_active: bool) -> None:
    result = record_failure(
        "observer:TimeoutError",
        cleanup_failure="cleanup:ConnectionError" if cleanup_failed else None,
        active_sessions=sessions_active,
    )
    assert result.primary_failure == "observer:TimeoutError"
    assert result.cleanup_failure == ("cleanup:ConnectionError" if cleanup_failed else None)
    assert result.outcome != "PASS"
    assert result.outcome == (
        "INCIDENT_ACTIVE_SESSIONS"
        if sessions_active
        else "INCIDENT_CLEANUP_UNVERIFIED"
        if cleanup_failed
        else "NOT_VERIFIED_PROBE_FAILURE"
    )


@pytest.mark.parametrize("primary", ["", " ", None, 1])
def test_missing_primary_evidence_denied(primary: object) -> None:
    with pytest.raises(RuntimeError, match="primary failure"):
        record_failure(primary)  # type: ignore[arg-type]


def test_cleanup_evidence_not_silently_accepted() -> None:
    with pytest.raises(RuntimeError, match="cleanup failure"):
        record_failure("observer:error", cleanup_failure="")


def test_active_session_must_be_boolean() -> None:
    with pytest.raises(RuntimeError, match="session evidence"):
        record_failure("observer:error", active_sessions=1)  # type: ignore[arg-type]
