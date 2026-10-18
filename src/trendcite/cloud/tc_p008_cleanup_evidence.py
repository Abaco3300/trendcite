"""Fail-closed verification of TC-P008 hosted probe cleanup evidence.

Pure validation only: this module neither connects to nor modifies PostgreSQL.
"""

from collections.abc import Mapping


def verify_probe_cleanup(evidence: Mapping[str, object]) -> dict[str, str]:
    """Require run-specific cleanup, closed sessions and an empty readback."""
    required_true = (
        "target_isolated",
        "cleanup_targeted",
        "independent_readback",
        "sessions_closed",
    )
    for field in required_true:
        if evidence.get(field) is not True:
            raise RuntimeError(f"TC-P008 cleanup unverified: {field}")
    for field in ("probe_run", "probe_key"):
        value = evidence.get(field)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"TC-P008 cleanup unverified: {field}")
    count = evidence.get("remaining_rows")
    if type(count) is not int or count != 0:
        raise RuntimeError("TC-P008 cleanup unverified: remaining_rows")
    return {"cleanup_contract": "PASS", "hosted_cleanup": "NOT_VERIFIED"}
