"""Gated synthetic Queue concurrency trace contract."""

from types import SimpleNamespace

from tests.test_tc_p008_queue_handler_contract import Message, _handler, _run


def test_nonprod_concurrency_trace_starts_and_finishes_before_ack():
    handler, ns = _handler()
    steps = []

    class Store:
        async def start_synthetic_queue_invocation(self, **kwargs):
            steps.append(("start", kwargs))

        async def record_queue_once(self, **kwargs):
            steps.append(("record", kwargs))
            return True

        async def finish_synthetic_queue_invocation(self, **kwargs):
            steps.append(("finish", kwargs))

    async def sleep(seconds):
        assert seconds == 2
        steps.append(("sleep", seconds))

    ns.update(
        {
            "_store": lambda env: Store(),
            "asyncio": SimpleNamespace(sleep=sleep),
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="probe")),
            "datetime": SimpleNamespace(
                now=lambda utc: SimpleNamespace(replace=lambda **kw: "now")
            ),
            "UTC": object(),
        }
    )
    message = Message(
        {
            "workspace_id": "tenant",
            "logical_id": "tc-p008-concurrency-1",
            "delivery_id": "fixed",
            "kind": "tc_p008_concurrency_probe",
        }
    )
    env = SimpleNamespace(
        dark=False,
        TRENDCITE_RUNTIME_ROLE="trendcite_nonprod_runtime",
        TRENDCITE_TC_P008_CONCURRENCY_TRACE="nonprod-enabled",
    )
    _run(handler(SimpleNamespace(messages=[message]), env))
    assert [s[0] for s in steps] == ["start", "sleep", "record", "finish"]
    assert steps[0][1]["invocation_id"] == steps[3][1]["invocation_id"]
    assert message.actions == ["ack"]
