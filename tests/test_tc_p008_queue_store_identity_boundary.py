"""Isolated tests of the actual Postgres queue ledger method across store instances.

These tests do not claim a real concurrent DB run or Cloudflare crash recovery.
"""

import ast
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _method():
    source = (ROOT / "src/trendcite/cloud/db/postgres.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "record_queue_once"
    ]
    assert len(found) == 1
    node = found[0]
    cls = ast.ClassDef(name="Ledger", bases=[], keywords=[], body=[node], decorator_list=[])
    scope = {"datetime": datetime}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),
            "real_queue_ledger",
            "exec",
        ),
        scope,
    )
    return scope["Ledger"]


def _drive(coro):
    try:
        coro.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Unexpected external I/O")


class DurableFake:
    def __init__(self):
        self.by_delivery = {}
        self.by_logical = {}

    async def fetchrow(self, statement, *args):
        if "INSERT INTO" in statement:
            delivery, workspace, logical, _kind, _timestamp = args
            key = (workspace, logical)
            if delivery in self.by_delivery or key in self.by_logical:
                return None
            self.by_delivery[delivery] = key
            self.by_logical[key] = delivery
            return {"delivery_id": delivery}
        workspace, logical = args
        delivery = self.by_logical.get((workspace, logical))
        return None if delivery is None else {"delivery_id": delivery}


def _store(db):
    ledger = _method()()

    @asynccontextmanager
    async def transaction():
        yield db

    ledger._transaction = transaction
    return ledger


def _record(store, delivery, workspace, logical):
    return _drive(
        store.record_queue_once(
            delivery_id=delivery,
            workspace_id=workspace,
            logical_id=logical,
            kind="synthetic_probe",
            first_seen_at=datetime.now(UTC),
        )
    )


def test_new_store_after_simulated_restart_does_not_duplicate_logical_job():
    database = DurableFake()
    assert _record(_store(database), "delivery-1", "tenant-a", "job-1") is True
    assert _record(_store(database), "delivery-2", "tenant-a", "job-1") is False
    assert len(database.by_logical) == 1


def test_delivery_id_collision_with_different_job_fails_closed():
    database = DurableFake()
    assert _record(_store(database), "same-delivery", "tenant-a", "job-1") is True
    with pytest.raises(RuntimeError, match="queue delivery identity collision"):
        _record(_store(database), "same-delivery", "tenant-a", "job-2")
    assert len(database.by_logical) == 1


def test_tenant_scoped_logical_idempotency():
    database = DurableFake()
    assert _record(_store(database), "d-a", "tenant-a", "job-1") is True
    assert _record(_store(database), "d-b", "tenant-b", "job-1") is True
    assert len(database.by_logical) == 2


def test_same_delivery_and_logical_identity_is_duplicate():
    database = DurableFake()
    assert _record(_store(database), "same", "tenant-a", "job-1") is True
    assert _record(_store(database), "same", "tenant-a", "job-1") is False
    assert len(database.by_logical) == 1


def test_delivery_id_shared_across_tenants_fails_closed():
    database = DurableFake()
    assert _record(_store(database), "shared", "tenant-a", "job") is True
    with pytest.raises(RuntimeError, match="queue delivery identity collision"):
        _record(_store(database), "shared", "tenant-b", "job")
    assert len(database.by_logical) == 1


def test_different_logical_jobs_in_same_workspace_remain_distinct():
    database = DurableFake()
    assert _record(_store(database), "first", "tenant-a", "job-a") is True
    assert _record(_store(database), "second", "tenant-a", "job-b") is True
    assert len(database.by_logical) == 2
