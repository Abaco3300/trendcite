"""End-to-end offline active-backend safety test."""

import threading

import pytest

from trendcite.cloud.tc_p008_hosted_runner import _run_probe_with_injected_connections


class Connection:
    def __init__(self, factory, kind):
        self.factory = factory
        self.kind = kind

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        if "pg_stat_activity" in sql:
            return self
        if "pg_cancel_backend" in sql:
            self.factory.cancelled.append(params[0])
            if self.factory.clear_after_cancellation and len(self.factory.cancelled) == 2:
                self.factory.active = False
            self.result = [(True,)]
            return self
        if sql == "SELECT pg_backend_pid()":
            self.result = [(101 if self.kind == "holder" else 202,)]
        elif "INSERT INTO tc_p008_isolated" in sql:
            self.result = [("winner",)] if self.kind == "holder" else []
        elif "pg_blocking_pids" in sql:
            self.result = [([101],)]
        elif "SELECT contender FROM tc_p008_isolated" in sql:
            self.result = [("holder",)]
        elif "SELECT count(*) FROM tc_p008_isolated" in sql:
            self.result = [(0,)]
        elif "DELETE FROM tc_p008_isolated" in sql:
            self.factory.deleted = True
            self.result = []
        else:
            self.result = []
        return self

    def fetchone(self):
        if self.kind == "backend" and self.factory.active:
            return (1,)
        if self.kind == "backend":
            return (0,)
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result

    def commit(self):
        pass

    def close(self):
        self.factory.closed_roles.append(self.kind)


class Connections:
    def __init__(self):
        self.deleted = False
        self.closed_roles = []
        self.active = True
        self.cancelled = []
        self.clear_after_cancellation = False
        self.main_count = 0
        self.thread_roles = {}
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            if threading.current_thread() is threading.main_thread():
                self.main_count += 1
                kind = (
                    ["observer", "backend", "cancel", "cancel", "backend", "cleanup", "audit"][
                        self.main_count - 1
                    ]
                    if self.active or self.cancelled
                    else ["observer", "backend", "cleanup", "audit"][self.main_count - 1]
                )
            else:
                name = threading.current_thread().name
                if name not in self.thread_roles:
                    self.thread_roles[name] = "holder" if not self.thread_roles else "contender"
                kind = self.thread_roles[name]
        return Connection(self, kind)


def test_live_backend_blocks_cleanup_despite_finished_threads():
    factory = Connections()
    with pytest.raises(RuntimeError, match="backend cancellation NOT_VERIFIED"):
        _run_probe_with_injected_connections(factory)
    assert factory.deleted is False
    assert factory.main_count == 5


def test_zero_backends_allows_scoped_cleanup_but_never_hosted_attestation():
    factory = Connections()
    factory.active = False
    evidence = _run_probe_with_injected_connections(factory)
    assert evidence["hosted_certification"] == "NOT_VERIFIED_PENDING_INDEPENDENT_REVIEW"
    assert evidence["contention_contract"] == "PASS"
    assert evidence["cleanup_contract"] == "PASS"
    assert evidence["winner"] == "holder"
    assert evidence["durable_count"] == 1
    assert evidence["independent_audit_remaining_rows"] == 0
    assert factory.deleted is True
    assert factory.main_count == 4
    assert sorted(factory.closed_roles) == sorted(
        ["holder", "contender", "observer", "backend", "cleanup", "audit"]
    )


def test_cancelled_backends_must_disappear_before_cleanup():
    factory = Connections()
    factory.clear_after_cancellation = True
    evidence = _run_probe_with_injected_connections(factory)
    assert evidence["hosted_certification"] == "NOT_VERIFIED_PENDING_INDEPENDENT_REVIEW"
    assert sorted(factory.cancelled) == [101, 202]
    assert factory.deleted is True
    assert sorted(factory.closed_roles) == sorted(
        [
            "holder",
            "contender",
            "observer",
            "backend",
            "cancel",
            "cancel",
            "backend",
            "cleanup",
            "audit",
        ]
    )
