"""Fail-closed checks of dedicated TC-P008 Worker/Queue identity."""

from copy import deepcopy

import pytest
from scripts.tc_p008_isolated_fault_config_gate import validate_isolated_fault_config

GOOD = {
    "name": "trendcite-tcp008-fault-worker",
    "workers_dev": False,
    "vars": {"TC_P008_FAULT_SANDBOX": "isolated-dark"},
    "queues": {
        "producers": [{"binding": "PROBE_QUEUE", "queue": "trendcite-tcp008-fault-queue"}],
        "consumers": [
            {
                "queue": "trendcite-tcp008-fault-queue",
                "dead_letter_queue": "trendcite-tcp008-fault-dlq",
                "max_batch_size": 1,
                "max_retries": 1,
            }
        ],
    },
}


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
