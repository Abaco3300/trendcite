"""Synthetic-only backend cancellation contract; no hosted execution authority."""

from collections.abc import Callable


def cancel_and_verify_backends(
    pids: tuple[int, int],
    *,
    cancel: Callable[[int], bool],
    verify_absent: Callable[[tuple[int, int]], bool],
) -> str:
    """Try cancellation for both backends, then independently require absence.

    Cancellation failure is not itself evidence of backend activity: a backend
    may have already exited. Verification must still be independently checked.
    """
    if (
        len(pids) != 2
        or any(type(pid) is not int or pid <= 0 for pid in pids)
        or pids[0] == pids[1]
    ):
        raise RuntimeError("invalid backend identities")
    errors: list[str] = []
    for pid in pids:
        try:
            if cancel(pid) is not True:
                errors.append("cancel_not_confirmed")
        except Exception:
            errors.append("cancel_failed")
    try:
        absent = verify_absent(pids) is True
    except Exception:
        absent = False
    if not absent:
        raise RuntimeError("backend termination NOT_VERIFIED: " + ",".join(errors))
    return "TERMINATION_OBSERVED_NOT_HOSTED_ATTESTED"
