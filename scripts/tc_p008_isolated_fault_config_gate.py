"""Offline guard for proposed TC-P008 fault-injection Worker configuration.

This does not deploy or access Cloudflare and does not certify provider behavior.
"""

import json
from pathlib import Path

BLOCKED_NAMES = {
    "trendcite-nonprod-runtime",
    "trendcite-prod-runtime",
    "trendcite-nonprod-queue",
    "trendcite-nonprod-dlq",
    "trendcite-prod-queue",
    "trendcite-prod-dlq",
}


def validate_isolated_fault_config(config: dict) -> None:
    if not isinstance(config, dict) or set(config) != {
        "name",
        "workers_dev",
        "vars",
        "queues",
        "d1_databases",
    }:
        raise RuntimeError("unexpected Worker configuration fields")
    name = config.get("name")
    if name != "trendcite-tcp008-fault-worker":
        raise RuntimeError("dedicated TC-P008 Worker identity required")
    if name in BLOCKED_NAMES:
        raise RuntimeError("shared Worker forbidden")
    if config.get("workers_dev") is not False:
        raise RuntimeError("public routing forbidden")
    vars_ = config.get("vars", {})
    if vars_ != {
        "TC_P008_FAULT_SANDBOX": "isolated-dark",
        "TC_P008_D1_NAME": "trendcite-tcp008-fault-d1",
    }:
        raise RuntimeError("isolated-dark guard required")
    d1 = config.get("d1_databases")
    if d1 != [
        {
            "binding": "FAULT_DB",
            "database_name": "trendcite-tcp008-fault-d1",
            "database_id": "bb27daa5-3f9e-488d-aa55-27c62a6dd325",
        }
    ]:
        raise RuntimeError("dedicated TC-P008 D1 binding required")
    queues = config.get("queues")
    if not isinstance(queues, dict) or set(queues) != {"producers", "consumers"}:
        raise RuntimeError("dedicated Queue required")
    producers = queues.get("producers")
    consumers = queues.get("consumers")
    if not isinstance(producers, list) or len(producers) != 1:
        raise RuntimeError("exactly one dedicated producer required")
    if not isinstance(consumers, list) or len(consumers) != 1:
        raise RuntimeError("exactly one dedicated consumer required")
    if not isinstance(producers[0], dict) or set(producers[0]) != {"binding", "queue"}:
        raise RuntimeError("unexpected producer configuration")
    if producers[0]["binding"] != "PROBE_QUEUE":
        raise RuntimeError("dedicated producer binding required")
    if not isinstance(consumers[0], dict) or set(consumers[0]) != {
        "queue",
        "dead_letter_queue",
        "max_batch_size",
        "max_retries",
    }:
        raise RuntimeError("unexpected consumer configuration")
    prod = producers[0].get("queue")
    cons = consumers[0].get("queue")
    dlq = consumers[0].get("dead_letter_queue")
    if (
        prod != "trendcite-tcp008-fault-queue"
        or cons != prod
        or dlq != "trendcite-tcp008-fault-dlq"
        or any(q in BLOCKED_NAMES for q in (prod, cons, dlq))
    ):
        raise RuntimeError("independent Queue and DLQ required")
    if (
        type(consumers[0].get("max_batch_size")) is not int
        or consumers[0]["max_batch_size"] != 1
        or type(consumers[0].get("max_retries")) is not int
        or consumers[0]["max_retries"] != 1
    ):
        raise RuntimeError("bounded fault delivery required")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("duplicate JSON key prohibited")
        result[key] = value
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    validate_isolated_fault_config(
        json.loads(args.config.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    )
    print("TC_P008_ISOLATION_CONFIG_PASS")
    print("HOSTED_EXECUTION_NOT_ATTEMPTED")


if __name__ == "__main__":
    main()
