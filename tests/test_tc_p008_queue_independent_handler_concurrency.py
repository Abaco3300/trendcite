"""Offline overlapping Queue handler invocations; not hosted multi-consumer evidence."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from tests.test_tc_p008_queue_handler_contract import Message, _handler


class PauseAtInsert:
    def __await__(self):
        yield "at-durable-boundary"
        return None


def test_overlapping_independent_invocations_commit_only_one_logical_effect():
    handler, ns = _handler()
    persisted = set()
    starts = []

    class SharedDurableStore:
        async def record_queue_once(self, **kwargs):
            starts.append(kwargs["delivery_id"])
            await PauseAtInsert()
            identity = (kwargs["workspace_id"], kwargs["logical_id"])
            if identity in persisted:
                return False
            persisted.add(identity)
            return True

    ns.update(
        {
            "_store": lambda env: SharedDurableStore(),
            "uuid": SimpleNamespace(uuid4=uuid4),
            "datetime": datetime,
            "UTC": UTC,
        }
    )
    payload = {
        "workspace_id": "tenant",
        "logical_id": "tc-p008-independent-invocations-001",
        "kind": "record",
    }
    a, b = Message(payload), Message(payload)
    env = SimpleNamespace(dark=False)
    ca = handler(SimpleNamespace(messages=[a]), env)
    cb = handler(SimpleNamespace(messages=[b]), env)

    # Both handlers have entered the persistence boundary before either commits.
    assert ca.send(None) == "at-durable-boundary"
    assert cb.send(None) == "at-durable-boundary"
    for coroutine in (ca, cb):
        try:
            coroutine.send(None)
        except StopIteration:
            pass
        else:
            raise AssertionError("handler did not finish")

    assert len(starts) == 2
    assert len(set(starts)) == 2
    assert persisted == {("tenant", "tc-p008-independent-invocations-001")}
    assert a.actions == ["ack"]
    assert b.actions == ["ack"]
