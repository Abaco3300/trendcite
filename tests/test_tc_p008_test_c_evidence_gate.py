"""Transport ACK loss cannot be inferred from an application exception."""

from copy import deepcopy

import pytest
from scripts.tc_p008_test_c_evidence_gate import assess

RUN = "123e4567-e89b-42d3-a456-426614174000"
GOOD = {
    "queue": "trendcite-tcp008-fault-queue",
    "database_id": "bb27daa5-3f9e-488d-aa55-27c62a6dd325",
    "run_id": RUN,
    "transport_ack_loss": {
        "source": "cloudflare_broker_transport",
        "message_id": "message-1",
        "run_id": RUN,
        "provider_event_id": "provider-trace",
        "reason": "ack_not_received",
    },
    "delivery_attempts": [
        {
            "source": "cloudflare_queue_delivery",
            "message_id": "message-1",
            "run_id": RUN,
            "attempt": 1,
        },
        {
            "source": "cloudflare_queue_delivery",
            "message_id": "message-1",
            "run_id": RUN,
            "attempt": 2,
        },
    ],
    "durable_readback": {
        "source": "cloudflare_d1_independent_query",
        "run_id": RUN,
        "row_count": 1,
        "phase": "committed",
    },
}


def test_claim_never_certifies_itself() -> None:
    result = assess(GOOD)
    assert result["status"] == "EVIDENCE_COMPLETE_PENDING_INDEPENDENT_AUTHENTICATION"
    assert result["hosted_certification"] == "NOT_VERIFIED"


@pytest.mark.parametrize(
    "path,bad",
    [
        (("transport_ack_loss", "source"), "application_exception"),
        (("transport_ack_loss", "reason"), "consumer_threw_exception"),
        (("transport_ack_loss", "provider_event_id"), ""),
        (("durable_readback", "row_count"), 2),
        (("durable_readback", "source"), "worker_self_report"),
        (("delivery_attempts", 1, "message_id"), "other-message"),
        (("delivery_attempts", 1, "attempt"), 1),
        (("delivery_attempts", 1, "attempt"), True),
    ],
)
def test_false_transport_claim_rejected(path, bad) -> None:
    value = deepcopy(GOOD)
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    assert assess(value)["status"] == "NOT_VERIFIED"


def test_existing_postcommit_exception_evidence_is_not_ack_loss() -> None:
    value = deepcopy(GOOD)
    value["transport_ack_loss"] = {
        "source": "cloudflare_queue_delivery",
        "reason": "application_exception",
        "run_id": RUN,
        "message_id": "message-1",
        "provider_event_id": "attempt-log",
    }
    assert assess(value)["status"] == "NOT_VERIFIED"
