"""Fail-closed checks of dedicated TC-P008 Worker/Queue identity."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from scripts.tc_p008_isolated_fault_config_gate import (
    reject_duplicate_keys,
    validate_isolated_fault_config,
)

MANIFEST = (
    Path(__file__).resolve().parents[1] / "deploy/cloudflare/tc_p008_fault_isolation_manifest.json"
)
GOOD = json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_dedicated_synthetic_configuration_passes() -> None:
    validate_isolated_fault_config(GOOD)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.update(name="trendcite-nonprod-runtime"),
        lambda c: c.update(name="trendcite-tcp008-foreign-worker"),
        lambda c: c["queues"]["producers"][0].update(queue="trendcite-tcp008-foreign-queue"),
        lambda c: c["queues"]["consumers"][0].update(
            dead_letter_queue="trendcite-tcp008-foreign-dlq"
        ),
        lambda c: c.update(workers_dev=True),
        lambda c: c.update(route=""),
        lambda c: c.update(triggers={}),
        lambda c: c.update(hyperdrive=[]),
        lambda c: c.update(main="src/main.py"),
        lambda c: c["queues"].update(extra=[]),
        lambda c: c["queues"]["producers"][0].update(extra="unsafe"),
        lambda c: c["queues"]["consumers"][0].update(extra="unsafe"),
        lambda c: c["queues"]["producers"][0].update(binding="SHARED"),
        lambda c: c.update(routes=["example.com/*"]),
        lambda c: c.update(hyperdrive=[{"id": "shared"}]),
        lambda c: c.update(vars={"TRENDCITE_CUSTOMER_MUTATIONS": "enabled"}),
        lambda c: c["queues"]["producers"][0].update(queue="trendcite-nonprod-queue"),
        lambda c: c["queues"]["consumers"][0].update(dead_letter_queue="trendcite-nonprod-dlq"),
        lambda c: c["queues"]["consumers"][0].update(max_batch_size=5),
        lambda c: c["queues"]["consumers"][0].update(max_retries=2),
        lambda c: c["queues"]["consumers"][0].update(
            dead_letter_queue="trendcite-tcp008-fault-queue"
        ),
    ],
)
def test_shared_or_unbounded_configuration_denied(mutate) -> None:
    config = deepcopy(GOOD)
    mutate(config)
    with pytest.raises(RuntimeError):
        validate_isolated_fault_config(config)


@pytest.mark.parametrize("field", ["max_batch_size", "max_retries"])
def test_bool_not_accepted_as_integer_one(field) -> None:
    config = deepcopy(GOOD)
    config["queues"]["consumers"][0][field] = True
    with pytest.raises(RuntimeError, match="bounded fault"):
        validate_isolated_fault_config(config)


def test_duplicate_manifest_keys_rejected() -> None:
    with pytest.raises(RuntimeError, match="duplicate JSON"):
        json.loads('{"name":"dedicated","name":"shared"}', object_pairs_hook=reject_duplicate_keys)
