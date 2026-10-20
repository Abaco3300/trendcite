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
    name = config.get("name")
    if not isinstance(name, str) or not name.startswith("trendcite-tcp008-"):
        raise RuntimeError("dedicated TC-P008 Worker identity required")
    if name in BLOCKED_NAMES:
        raise RuntimeError("shared Worker forbidden")
    if config.get("routes") or config.get("route") or config.get("workers_dev") is not False:
        raise RuntimeError("public routing forbidden")
    if config.get("triggers") or config.get("hyperdrive") or config.get("assets"):
        raise RuntimeError("shared runtime bindings forbidden")
    vars_ = config.get("vars", {})
    if vars_ != {"TC_P008_FAULT_SANDBOX": "isolated-dark"}:
        raise RuntimeError("isolated-dark guard required")
    queues = config.get("queues")
    if not isinstance(queues, dict):
        raise RuntimeError("dedicated Queue required")
    producers = queues.get("producers")
    consumers = queues.get("consumers")
    if not isinstance(producers, list) or len(producers) != 1:
        raise RuntimeError("exactly one dedicated producer required")
    if not isinstance(consumers, list) or len(consumers) != 1:
        raise RuntimeError("exactly one dedicated consumer required")
    prod = producers[0].get("queue")
    cons = consumers[0].get("queue")
    dlq = consumers[0].get("dead_letter_queue")
    if (
        not all(isinstance(q, str) and q.startswith("trendcite-tcp008-") for q in (prod, cons, dlq))
        or len({prod, dlq}) != 2
        or prod != cons
        or any(q in BLOCKED_NAMES for q in (prod, cons, dlq))
    ):
        raise RuntimeError("independent Queue and DLQ required")
    if consumers[0].get("max_batch_size") != 1 or consumers[0].get("max_retries") != 1:
        raise RuntimeError("bounded fault delivery required")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    validate_isolated_fault_config(json.loads(args.config.read_text(encoding="utf-8")))
    print("TC_P008_ISOLATION_CONFIG_PASS")
    print("HOSTED_EXECUTION_NOT_ATTEMPTED")


if __name__ == "__main__":
    main()
