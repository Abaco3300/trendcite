"""Fail-closed session rollback and close helper for isolated TC-P008 probes.

Offline and injectable; not wired into the disabled hosted executor.
"""


def abort_session(session: object) -> None:
    """Attempt rollback and close independently; never hide either failure."""
    failures: list[str] = []
    for operation in ("rollback", "close"):
        method = getattr(session, operation, None)
        if not callable(method):
            failures.append(operation + "_unavailable")
            continue
        try:
            method()
        except Exception:
            failures.append(operation + "_failed")
    if failures:
        raise RuntimeError("TC-P008 session abort incomplete: " + ",".join(failures))
