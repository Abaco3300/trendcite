"""Offline-only recovery orchestration matrix: no SQL, no network."""

import itertools

import pytest

from trendcite.cloud.tc_p008_termination_harness import reconcile_stalled_probe


@pytest.mark.parametrize("outcomes", list(itertools.product((False, True), repeat=6)))
def test_all_recovery_combinations_fail_closed_or_require_review(
    outcomes: tuple[bool, ...],
) -> None:
    names = (
        "cancel",
        "rollback",
        "close",
        "verify_sessions_terminated",
        "cleanup",
        "verify_zero_rows",
    )
    operations = {name: (lambda value=value: value) for name, value in zip(names, outcomes)}
    report = reconcile_stalled_probe(**operations)
    assert report.outcome != "PASS"
    assert report.events[:4] == names[:4]
    if not outcomes[3]:
        assert report.outcome == "INCIDENT_ACTIVE_SESSIONS"
        assert "cleanup" not in report.events
    elif not outcomes[4]:
        assert report.outcome == "INCIDENT_CLEANUP_UNVERIFIED"
        assert "verify_zero_rows" not in report.events
    elif all(outcomes):
        assert report.outcome == "REQUIRES_INDEPENDENT_HOSTED_REVIEW"
        assert report.disposition is None
    elif not outcomes[5]:
        assert report.outcome == "INCIDENT_CLEANUP_UNVERIFIED"


def test_cancel_failure_does_not_skip_rollback_and_close() -> None:
    calls = []

    def failed_cancel() -> bool:
        calls.append("cancel")
        raise TimeoutError("injected")

    def rollback() -> bool:
        calls.append("rollback")
        return True

    def close() -> bool:
        calls.append("close")
        return True

    report = reconcile_stalled_probe(
        cancel=failed_cancel,
        rollback=rollback,
        close=close,
        verify_sessions_terminated=lambda: True,
        cleanup=lambda: True,
        verify_zero_rows=lambda: True,
    )
    assert calls == ["cancel", "rollback", "close"]
    assert report.disposition is not None
    assert report.disposition.primary_failure == "recovery:cancel"
    assert report.outcome != "PASS"
