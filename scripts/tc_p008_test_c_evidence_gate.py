"""Fail-closed completeness gate for TC-P008 transport-level lost ACK.

Claims in arbitrary JSON are never authenticated provider evidence and do
not certify the hosted criterion, even if all shape checks pass.
"""

import argparse
import json
import uuid
from pathlib import Path

EXPECTED_QUEUE = "trendcite-tcp008-fault-queue"
EXPECTED_DATABASE = "bb27daa5-3f9e-488d-aa55-27c62a6dd325"
FIELDS = {
    "queue",
    "database_id",
    "run_id",
    "transport_ack_loss",
    "delivery_attempts",
    "durable_readback",
}


def assess(document: object) -> dict[str, object]:
    reasons: list[str] = []
    if not isinstance(document, dict) or set(document) != FIELDS:
        return {
            "hosted_certification": "NOT_VERIFIED",
            "status": "NOT_VERIFIED",
            "reasons": ["invalid_evidence_shape"],
        }
    if document["queue"] != EXPECTED_QUEUE or document["database_id"] != EXPECTED_DATABASE:
        reasons.append("isolation_mismatch")
    run_id = document["run_id"]
    try:
        if not isinstance(run_id, str) or str(uuid.UUID(run_id)) != run_id.lower():
            raise ValueError
    except (ValueError, AttributeError):
        reasons.append("invalid_run_id")
    loss = document["transport_ack_loss"]
    if not isinstance(loss, dict) or set(loss) != {
        "source",
        "message_id",
        "run_id",
        "provider_event_id",
        "reason",
    }:
        reasons.append("transport_ack_loss_not_observed")
    elif (
        loss["source"] != "cloudflare_broker_transport"
        or loss["run_id"] != run_id
        or loss["reason"] != "ack_not_received"
        or not isinstance(loss["provider_event_id"], str)
        or not loss["provider_event_id"].strip()
        or not isinstance(loss["message_id"], str)
        or not loss["message_id"].strip()
    ):
        reasons.append("transport_ack_loss_unsubstantiated")
    attempts = document["delivery_attempts"]
    if (
        not isinstance(attempts, list)
        or len(attempts) < 2
        or any(
            not isinstance(item, dict) or set(item) != {"message_id", "run_id", "attempt", "source"}
            for item in attempts
        )
    ):
        reasons.append("physical_redelivery_missing")
    elif (
        any(
            item["source"] != "cloudflare_queue_delivery"
            or item["run_id"] != run_id
            or not isinstance(item["message_id"], str)
            or not isinstance(item["attempt"], int)
            or isinstance(item["attempt"], bool)
            for item in attempts
        )
        or len({item["message_id"] for item in attempts}) != 1
        or [item["attempt"] for item in attempts] != list(range(1, len(attempts) + 1))
        or (isinstance(loss, dict) and attempts[0]["message_id"] != loss.get("message_id"))
    ):
        reasons.append("physical_redelivery_inconsistent")
    durable = document["durable_readback"]
    if not isinstance(durable, dict) or set(durable) != {"source", "run_id", "row_count", "phase"}:
        reasons.append("independent_durability_missing")
    elif (
        durable["source"] != "cloudflare_d1_independent_query"
        or durable["run_id"] != run_id
        or type(durable["row_count"]) is not int
        or durable["row_count"] != 1
        or durable["phase"] != "committed"
    ):
        reasons.append("once_only_persistence_unsubstantiated")
    return {
        "hosted_certification": "NOT_VERIFIED",
        "reasons": reasons,
        "status": (
            "EVIDENCE_COMPLETE_PENDING_INDEPENDENT_AUTHENTICATION"
            if not reasons
            else "NOT_VERIFIED"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        result = assess(json.loads(args.evidence.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError):
        result = {
            "status": "NOT_VERIFIED",
            "hosted_certification": "NOT_VERIFIED",
            "reasons": ["unreadable_evidence"],
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "EVIDENCE_COMPLETE_PENDING_INDEPENDENT_AUTHENTICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
