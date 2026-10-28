"""TC-P008 offline-only failure disposition.

A failed probe must retain the incident evidence even if cleanup fails too.
This has no SQL or network behavior and never asserts hosted certification.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FailureDisposition:
    outcome: str
    primary_failure: str
    cleanup_failure: str | None
    active_sessions: bool


def record_failure(
    primary_failure: str,
    *,
    cleanup_failure: str | None = None,
    active_sessions: bool = False,
) -> FailureDisposition:
    if not isinstance(primary_failure, str) or not primary_failure.strip():
        raise RuntimeError("primary failure evidence required")
    if cleanup_failure is not None and (
        not isinstance(cleanup_failure, str) or not cleanup_failure.strip()
    ):
        raise RuntimeError("cleanup failure evidence invalid")
    if type(active_sessions) is not bool:
        raise RuntimeError("session evidence invalid")
    return FailureDisposition(
        outcome=(
            "INCIDENT_ACTIVE_SESSIONS"
            if active_sessions
            else "INCIDENT_CLEANUP_UNVERIFIED"
            if cleanup_failure
            else "NOT_VERIFIED_PROBE_FAILURE"
        ),
        primary_failure=primary_failure,
        cleanup_failure=cleanup_failure,
        active_sessions=active_sessions,
    )
