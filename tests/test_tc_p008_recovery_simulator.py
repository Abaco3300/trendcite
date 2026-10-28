"""TC-P008 recovery failure matrix. All callbacks are in-memory fakes."""

import itertools

import pytest

from trendcite.cloud.tc_p008_recovery_simulator import simulate_recovery


class FakeSession:
    def __init__(self, *, fail_rollback: bool = False, fail_close: bool = False):
        self.fail_rollback = fail_rollback
        self.fail_close = fail_close
        self.calls: list[str] = []

    def rollback(self) -> None:
        self.calls.append("rollback")
        if self.fail_rollback:
            raise RuntimeError("synthetic rollback failure")

    def close(self) -> None:
        self.calls.append("close")
        if self.fail_close:
            raise RuntimeError("synthetic close failure")


def returning(value: bool):
    def callback() -> bool:
        return value

    return callback


def failing() -> bool:
    raise RuntimeError("synthetic operation failure")


@pytest.mark.parametrize(
    ("observer", "cleanup", "audit", "rollback_failure", "close_failure"),
    list(itertools.product((False, True), repeat=5)),
)
def test_all_failure_combinations_are_not_hosted_pass(
    observer: bool,
    cleanup: bool,
    audit: bool,
    rollback_failure: bool,
    close_failure: bool,
) -> None:
    session = FakeSession(
        fail_rollback=rollback_failure,
        fail_close=close_failure,
    )
    result = simulate_recovery(
        session=session,
        observe=returning(observer),
        cleanup=returning(cleanup),
        independently_audit=returning(audit),
    )
    assert "PASS" not in result.classification
    assert session.calls == ["rollback", "close"]
    if rollback_failure or close_failure:
        assert result.abort_error
        assert result.classification == "INCIDENT_ACTIVE_SESSIONS"
    elif not cleanup or not audit:
        assert result.classification == "INCIDENT_CLEANUP_UNVERIFIED"
    elif not observer:
        assert result.classification == "NOT_VERIFIED_OBSERVER_FAILURE"
    else:
        assert result.classification == "REQUIRES_INDEPENDENT_HOSTED_REVIEW"


@pytest.mark.parametrize("phase", ["observe", "cleanup", "audit"])
def test_exceptions_never_skip_rollback_or_close(phase: str) -> None:
    session = FakeSession()
    callbacks = {
        "observe": returning(True),
        "cleanup": returning(True),
        "audit": returning(True),
    }
    callbacks[phase] = failing
    result = simulate_recovery(
        session=session,
        observe=callbacks["observe"],
        cleanup=callbacks["cleanup"],
        independently_audit=callbacks["audit"],
    )
    assert session.calls == ["rollback", "close"]
    assert result.classification != "REQUIRES_INDEPENDENT_HOSTED_REVIEW"


def test_cleanup_attempted_after_observer_failure() -> None:
    calls: list[str] = []
    session = FakeSession()

    def observe() -> bool:
        calls.append("observe")
        raise TimeoutError("synthetic observer timeout")

    def cleanup() -> bool:
        calls.append("cleanup")
        return True

    def audit() -> bool:
        calls.append("audit")
        return True

    result = simulate_recovery(
        session=session, observe=observe, cleanup=cleanup, independently_audit=audit
    )
    assert calls == ["observe", "cleanup", "audit"]
    assert result.observer_error
    assert result.classification == "NOT_VERIFIED_OBSERVER_FAILURE"


def test_audit_not_attempted_if_cleanup_failed() -> None:
    def forbidden_audit() -> bool:
        raise AssertionError("audit invoked despite failed cleanup")

    result = simulate_recovery(
        session=FakeSession(),
        observe=returning(True),
        cleanup=returning(False),
        independently_audit=forbidden_audit,
    )
    assert result.classification == "INCIDENT_CLEANUP_UNVERIFIED"
