"""TC-P008 offline execution harness for cancellation and cleanup incidents.

It does not open connections and cannot certify a hosted run. Each callback
is injected by local tests; no production or sandbox credentials are used.
"""

from collections.abc import Callable
from dataclasses import dataclass

from trendcite.cloud.tc_p008_failure_disposition import FailureDisposition, record_failure


@dataclass(frozen=True)
class TerminationReport:
    outcome: str
    disposition: FailureDisposition | None
    events: tuple[str, ...]


def reconcile_stalled_probe(
    *,
    cancel: Callable[[], bool],
    rollback: Callable[[], bool],
    close: Callable[[], bool],
    verify_sessions_terminated: Callable[[], bool],
    cleanup: Callable[[], bool],
    verify_zero_rows: Callable[[], bool],
) -> TerminationReport:
    """Always try each recovery stage; deny success without independent proof."""
    events: list[str] = []
    failed: list[str] = []

    def attempt(name: str, operation: Callable[[], bool]) -> bool:
        events.append(name)
        try:
            ok = operation() is True
        except Exception:
            ok = False
        if not ok:
            failed.append(name)
        return ok

    attempt("cancel", cancel)
    attempt("rollback", rollback)
    attempt("close", close)
    terminated = attempt("verify_sessions_terminated", verify_sessions_terminated)
    # Never write while participant backends might still hold the probe key.
    if terminated:
        cleaned = attempt("cleanup", cleanup)
        zero = attempt("verify_zero_rows", verify_zero_rows) if cleaned else False
    else:
        cleaned = zero = False

    if failed or not terminated or not cleaned or not zero:
        disposition = record_failure(
            "recovery:" + (failed[0] if failed else "unverified"),
            cleanup_failure="cleanup_unverified" if not cleaned or not zero else None,
            active_sessions=not terminated,
        )
        return TerminationReport(disposition.outcome, disposition, tuple(events))
    return TerminationReport("REQUIRES_INDEPENDENT_HOSTED_REVIEW", None, tuple(events))
