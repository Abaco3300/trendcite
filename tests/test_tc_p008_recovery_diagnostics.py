"""Preserve failure diagnostics through the offline coordinator."""

from trendcite.cloud.tc_p008_recovery_simulator import simulate_recovery


class FakeSession:
    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _ok() -> bool:
    return True


def _observer_failure() -> bool:
    raise TimeoutError("synthetic observer timeout")


def _cleanup_failure() -> bool:
    raise OSError("synthetic cleanup transport failure")


def test_coordinator_retains_observer_and_cleanup_incidents() -> None:
    result = simulate_recovery(
        session=FakeSession(),
        observe=_observer_failure,
        cleanup=_cleanup_failure,
        independently_audit=_ok,
    )
    assert result.disposition is not None
    assert result.disposition.primary_failure == "observer_exception"
    assert result.disposition.cleanup_failure == "cleanup_exception"
    assert result.classification == "INCIDENT_CLEANUP_UNVERIFIED"


def test_good_offline_shape_still_requires_hosted_review() -> None:
    result = simulate_recovery(
        session=FakeSession(),
        observe=_ok,
        cleanup=_ok,
        independently_audit=_ok,
    )
    assert result.disposition is None
    assert result.classification == "REQUIRES_INDEPENDENT_HOSTED_REVIEW"
