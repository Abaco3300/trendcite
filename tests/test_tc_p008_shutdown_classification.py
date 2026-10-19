"""Conservative result classification with synthetic shutdown outcomes."""

import itertools

import pytest

from trendcite.cloud.tc_p008_shutdown_classification import classify_shutdown


@pytest.mark.parametrize(
    ("observer", "cleanup", "closed", "zero"),
    list(itertools.product((False, True), repeat=4)),
)
def test_shutdown_never_certifies_hosted_pass(
    observer: bool, cleanup: bool, closed: bool, zero: bool
) -> None:
    result = classify_shutdown(
        observer_ok=observer,
        cleanup_ok=cleanup,
        sessions_closed=closed,
        audited_zero=zero,
    )
    assert result != "PASS"
    if not closed:
        assert result == "INCIDENT_ACTIVE_SESSIONS"
    elif not cleanup or not zero:
        assert result == "INCIDENT_CLEANUP_UNVERIFIED"
    elif not observer:
        assert result == "NOT_VERIFIED_OBSERVER_FAILURE"
    else:
        assert result == "REQUIRES_INDEPENDENT_HOSTED_REVIEW"


def test_non_boolean_values_rejected() -> None:
    with pytest.raises(RuntimeError, match="invalid shutdown evidence"):
        classify_shutdown(
            observer_ok=True,
            cleanup_ok=True,
            sessions_closed=True,
            audited_zero=1,
        )
