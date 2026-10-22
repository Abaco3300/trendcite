"""Offline-only TC-P008 recovery coordinator for simulated sessions.

This module performs no SQL and has no connection factory. It exercises the
rollback/close and result-classification contract independently of a live host.
"""

from collections.abc import Callable
from dataclasses import dataclass

from trendcite.cloud.tc_p008_failure_disposition import FailureDisposition, record_failure
from trendcite.cloud.tc_p008_session_abort import abort_session
from trendcite.cloud.tc_p008_shutdown_classification import classify_shutdown


@dataclass(frozen=True)
class RecoveryResult:
    classification: str
    observer_error: bool
    cleanup_error: bool
    abort_error: bool
    disposition: FailureDisposition | None


def simulate_recovery(
    *,
    session: object,
    observe: Callable[[], bool],
    cleanup: Callable[[], bool],
    independently_audit: Callable[[], bool],
) -> RecoveryResult:
    """Attempt cleanup after failures, then rollback and close without masking them.

    Only pre-supplied fakes may be passed. A result is evidence of local contract
    behavior, never a hosted execution attestation.
    """
    observer_ok = False
    cleanup_ok = False
    audited_zero = False
    observer_error = False
    cleanup_error = False
    abort_error = False

    try:
        observer_ok = observe() is True
    except Exception:
        observer_error = True

    try:
        cleanup_ok = cleanup() is True
    except Exception:
        cleanup_error = True

    if cleanup_ok:
        try:
            audited_zero = independently_audit() is True
        except Exception:
            cleanup_error = True

    try:
        abort_session(session)
    except RuntimeError:
        abort_error = True

    classification = classify_shutdown(
        observer_ok=observer_ok and not observer_error,
        cleanup_ok=cleanup_ok and not cleanup_error,
        sessions_closed=not abort_error,
        audited_zero=audited_zero,
    )
    disposition = None
    if observer_error or cleanup_error or abort_error:
        primary = (
            "observer_exception"
            if observer_error
            else "cleanup_exception"
            if cleanup_error
            else "session_abort_exception"
        )
        disposition = record_failure(
            primary,
            cleanup_failure="cleanup_exception" if cleanup_error else None,
            active_sessions=abort_error,
        )
    return RecoveryResult(
        classification=classification,
        observer_error=observer_error,
        cleanup_error=cleanup_error,
        abort_error=abort_error,
        disposition=disposition,
    )
