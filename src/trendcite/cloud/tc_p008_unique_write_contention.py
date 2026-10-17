"""Fail-closed classification of isolated unique-key contention observations."""

from collections.abc import Mapping


def validate_unique_write_contention(evidence: Mapping[str, object]) -> dict[str, str]:
    """Validate evidence shape without claiming a hosted probe occurred."""
    a = evidence.get("holder_pid")
    b = evidence.get("contender_pid")
    if type(a) is not int or type(b) is not int or a <= 0 or b <= 0 or a == b:
        raise RuntimeError("distinct PostgreSQL sessions not established")
    if evidence.get("blocking_pid") != a or evidence.get("blocked_pid") != b:
        raise RuntimeError("observed blocking not established")
    if evidence.get("holder_commit") is not True:
        raise RuntimeError("durable holder commit not established")
    if evidence.get("contender_insert_count") != 0:
        raise RuntimeError("loser outcome not established")
    if evidence.get("durable_count") != 1 or evidence.get("winner") != "holder":
        raise RuntimeError("single durable winner not established")
    if evidence.get("cleanup_count") != 0:
        raise RuntimeError("targeted cleanup not established")
    if evidence.get("isolated_nonprod") is not True:
        raise RuntimeError("isolated nonprod environment not established")
    return {"local_contract": "PASS", "hosted_unique_key_contention": "NOT_VERIFIED"}
