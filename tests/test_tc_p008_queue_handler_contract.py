"""Execute the deployed queue handler's actual AST with isolated fake boundaries.

No Cloudflare Queue, PostgreSQL, email provider, or production call occurs.
"""

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _run(coro):
    """Drive no-I/O mock coroutines without opening a socket/event loop."""
    try:
        coro.send(None)
    except StopIteration:
        return
    raise AssertionError("Unexpected asynchronous I/O in isolated Queue test")


def _handler():
    source = (ROOT / "deploy/cloudflare/src/main.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    worker = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "Default")
    queue = next(
        n for n in worker.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "queue"
    )
    class_node = ast.ClassDef(
        name="IsolatedWorker", bases=[], keywords=[], body=[queue], decorator_list=[]
    )
    namespace = {"_production_foundation_only": lambda env: env.dark, "json": json, "Any": Any}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[class_node], type_ignores=[])),
            "queue_handler_contract",
            "exec",
        ),
        namespace,
    )
    return namespace["IsolatedWorker"]().queue, namespace


class Message:
    def __init__(self, body):
        self.body = json.dumps(body)
        self.id = "synthetic-msg"
        self.attempts = 1
        self.actions = []

    def ack(self):
        self.actions.append("ack")

    def retry(self):
        self.actions.append("retry")


def test_dark_production_rejects_before_store_access():
    handler, ns = _handler()
    ns["_store"] = lambda env: (_ for _ in ()).throw(AssertionError("store accessed"))
    msg = Message({"workspace_id": "w", "logical_id": "i", "kind": "unknown"})
    try:
        _run(handler(SimpleNamespace(messages=[msg]), SimpleNamespace(dark=True)))
    except RuntimeError as exc:
        assert str(exc) == "production foundation is dark"
    else:
        raise AssertionError("DARK handler accepted a Queue event")
    assert msg.actions == []


def test_nonprod_persistence_then_ack_and_duplicate_ack():
    handler, ns = _handler()
    calls = []

    class Store:
        async def record_queue_once(self, **kwargs):
            calls.append(kwargs)
            return len(calls) == 1

    ns.update(
        {
            "_store": lambda env: Store(),
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="x")),
            "datetime": SimpleNamespace(
                now=lambda utc: SimpleNamespace(replace=lambda **kw: "now")
            ),
            "UTC": object(),
        }
    )
    msg1 = Message({"workspace_id": "tenant", "logical_id": "run", "kind": "record"})
    msg2 = Message({"workspace_id": "tenant", "logical_id": "run", "kind": "record"})
    _run(handler(SimpleNamespace(messages=[msg1, msg2]), SimpleNamespace(dark=False)))
    assert len(calls) == 2
    assert msg1.actions == ["ack"]
    assert msg2.actions == ["ack"]


def test_nonprod_store_failure_never_acknowledged():
    handler, ns = _handler()

    class Store:
        async def record_queue_once(self, **kwargs):
            raise RuntimeError("synthetic Postgres outage")

    class Audit:
        async def record_queue_failure(self, **kwargs):
            return None

    ns.update(
        {
            "_store": lambda env: Store(),
            "_automation_store": lambda env: Audit(),
            "_env_positive_int": lambda env, name, default: default,
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="x")),
            "datetime": SimpleNamespace(
                now=lambda utc: SimpleNamespace(replace=lambda **kw: "now")
            ),
            "UTC": object(),
        }
    )
    msg = Message({"workspace_id": "tenant", "logical_id": "run", "kind": "record"})
    _run(handler(SimpleNamespace(messages=[msg]), SimpleNamespace(dark=False)))
    assert msg.actions == ["retry"]


def test_failed_audit_still_retries_without_ack():
    handler, ns = _handler()
    observed = []

    class Store:
        async def record_queue_once(self, **kwargs):
            raise RuntimeError("synthetic persistence outage")

    class Audit:
        async def record_queue_failure(self, **kwargs):
            observed.append(kwargs)
            raise RuntimeError("synthetic audit outage")

    ns.update(
        {
            "_store": lambda env: Store(),
            "_automation_store": lambda env: Audit(),
            "_env_positive_int": lambda env, name, default: default,
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="x")),
            "datetime": SimpleNamespace(
                now=lambda utc: SimpleNamespace(replace=lambda **kw: "now")
            ),
            "UTC": object(),
        }
    )
    msg = Message({"workspace_id": "tenant", "logical_id": "bad", "kind": "record"})
    _run(handler(SimpleNamespace(messages=[msg]), SimpleNamespace(dark=False)))
    assert msg.actions == ["retry"]
    assert len(observed) == 1


def test_invalid_message_retries_and_does_not_block_following_valid_message():
    handler, ns = _handler()
    writes = []

    class Store:
        async def record_queue_once(self, **kwargs):
            writes.append(kwargs)
            return True

    ns.update(
        {
            "_store": lambda env: Store(),
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="x")),
            "datetime": SimpleNamespace(
                now=lambda utc: SimpleNamespace(replace=lambda **kw: "now")
            ),
            "UTC": object(),
        }
    )
    invalid = Message({"workspace_id": "tenant", "kind": "record"})
    valid = Message({"workspace_id": "tenant", "logical_id": "good", "kind": "record"})
    _run(handler(SimpleNamespace(messages=[invalid, valid]), SimpleNamespace(dark=False)))
    assert invalid.actions == ["retry"]
    assert valid.actions == ["ack"]
    assert len(writes) == 1
    assert writes[0]["logical_id"] == "good"


def test_ack_loss_after_commit_redelivery_is_deduplicated():
    """Exercise real handler twice with fake durable ledger and first ACK exception.

    This is a deterministic no-network test, NOT a broker-triggered E2E.
    """
    handler, ns = _handler()
    committed = set()
    effects = []

    class Store:
        async def record_queue_once(self, **kwargs):
            identity = (kwargs["workspace_id"], kwargs["logical_id"])
            if identity in committed:
                return False
            committed.add(identity)
            effects.append(identity)
            return True

    ns.update(
        {
            "_store": lambda env: Store(),
            "uuid": SimpleNamespace(uuid4=lambda: SimpleNamespace(hex="x")),
            "datetime": SimpleNamespace(
                now=lambda utc: SimpleNamespace(replace=lambda **kw: "now")
            ),
            "UTC": object(),
        }
    )
    payload = {
        "workspace_id": "tenant",
        "logical_id": "committed-job",
        "delivery_id": "transport-message",
        "kind": "record",
    }

    class LostAckMessage(Message):
        def ack(self):
            self.actions.append("ack-lost")
            raise RuntimeError("synthetic process termination after durable commit")

    # The current handler catches the ACK exception, then requests retry.
    # This is a synthetic lost-ACK exception, not a real process termination.
    first = LostAckMessage(payload)
    _run(handler(SimpleNamespace(messages=[first]), SimpleNamespace(dark=False)))

    redelivered = Message(payload)
    _run(handler(SimpleNamespace(messages=[redelivered]), SimpleNamespace(dark=False)))
    assert first.actions == ["ack-lost", "retry"]
    assert redelivered.actions == ["ack"]
    assert effects == [("tenant", "committed-job")]
