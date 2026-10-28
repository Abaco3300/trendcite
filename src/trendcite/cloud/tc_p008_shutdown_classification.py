"""Fail-closed result classification for TC-P008 hosted cleanup failures."""


def classify_shutdown(
    *, observer_ok: bool, cleanup_ok: bool, sessions_closed: bool, audited_zero: bool
) -> str:
    """Never promote interrupted or unverified runs to hosted PASS."""
    if not all(
        type(value) is bool for value in (observer_ok, cleanup_ok, sessions_closed, audited_zero)
    ):
        raise RuntimeError("invalid shutdown evidence")
    if not sessions_closed:
        return "INCIDENT_ACTIVE_SESSIONS"
    if not cleanup_ok or not audited_zero:
        return "INCIDENT_CLEANUP_UNVERIFIED"
    if not observer_ok:
        return "NOT_VERIFIED_OBSERVER_FAILURE"
    return "REQUIRES_INDEPENDENT_HOSTED_REVIEW"
