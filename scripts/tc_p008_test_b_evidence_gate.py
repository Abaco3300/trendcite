"""Offline TC-P008 B evidence completeness gate; never certifies a hosted event.

Untrusted JSON from a caller cannot independently authenticate provider logs.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

EXPECTED_DATABASE = "bb27daa5-3f9e-488d-aa55-27c62a6dd325"
EXPECTED_WORKER = "trendcite-tcp008-fault-worker"
ALLOWED_TERMINATIONS = {"exceededCpu", "exceededMemory"}
FIELDS = {"worker", "database_id", "run_id", "provider_event", "d1_readback"}


def parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone required")
    return dt.astimezone(UTC)


def assess_evidence(document: object) -> dict[str, object]:
    reasons = []
    if not isinstance(document, dict) or set(document) != FIELDS:
        return {"status": "NOT_VERIFIED", "reasons": ["invalid_evidence_shape"]}
    if document["worker"] != EXPECTED_WORKER or document["database_id"] != EXPECTED_DATABASE:
        reasons.append("wrong_isolation_target")
    run_id = document["run_id"]
    import uuid

    try:
        if not isinstance(run_id, str) or str(uuid.UUID(run_id)) != run_id.lower():
            raise ValueError
    except (ValueError, AttributeError):
        reasons.append("invalid_run_id")
    event, readback = document["provider_event"], document["d1_readback"]
    if not isinstance(event, dict) or set(event) != {
        "source",
        "worker",
        "run_id",
        "outcome",
        "timestamp",
        "event_id",
    }:
        reasons.append("provider_event_missing")
    elif (
        event["source"] != "cloudflare_workers_trace"
        or event["worker"] != EXPECTED_WORKER
        or event["run_id"] != run_id
        or not isinstance(event["outcome"], str)
        or event["outcome"] not in ALLOWED_TERMINATIONS
        or not isinstance(event["event_id"], str)
        or not event["event_id"].strip()
    ):
        reasons.append("provider_termination_unsubstantiated")
    if not isinstance(readback, dict) or set(readback) != {
        "source",
        "run_id",
        "row_count",
        "phase",
        "timestamp",
    }:
        reasons.append("independent_readback_missing")
    elif (
        readback["source"] != "cloudflare_d1_independent_query"
        or readback["run_id"] != run_id
        or type(readback["row_count"]) is not int
        or readback["row_count"] != 1
        or readback["phase"] != "committed"
    ):
        reasons.append("durable_once_only_unsubstantiated")
    if not reasons:
        try:
            if parse_time(event["timestamp"]) > parse_time(readback["timestamp"]):
                reasons.append("readback_precedes_provider_event")
        except (ValueError, TypeError, OverflowError):
            reasons.append("invalid_timestamps")
    return {
        "status": "NOT_VERIFIED"
        if reasons
        else "EVIDENCE_COMPLETE_PENDING_INDEPENDENT_AUTHENTICATION",
        "reasons": reasons,
        "hosted_certification": "NOT_VERIFIED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.evidence.read_text(encoding="utf-8"))
        result = assess_evidence(data)
    except (OSError, ValueError, UnicodeError):
        result = {
            "status": "NOT_VERIFIED",
            "reasons": ["unreadable_evidence"],
            "hosted_certification": "NOT_VERIFIED",
        }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "EVIDENCE_COMPLETE_PENDING_INDEPENDENT_AUTHENTICATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
