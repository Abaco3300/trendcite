"""Offline recovery of stalled thread/backends, without a hosted connection."""

import pytest

from tests.test_tc_p008_full_offline_runner import Connection
from trendcite.cloud.tc_p008_hosted_runner import _recover_stalled_participants


class Connections:
    def __init__(self, clear_after_cancellation=False):
        self.active = True
        self.clear_after_cancellation = clear_after_cancellation
        self.cancelled = []
        self.closed_roles = []
        self.deleted = False
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return Connection(self, "backend" if self.calls == 3 else "cancel")


class Thread:
    def __init__(self, live=False):
        self.live = live
        self.joins = []

    def join(self, timeout):
        self.joins.append(timeout)

    def is_alive(self):
        return self.live


def test_unverified_backend_identities_never_connect():
    calls = []
    with pytest.raises(RuntimeError, match="stalled backends unverified"):
        _recover_stalled_participants(lambda: calls.append(1), [Thread()], (101, None))
    assert calls == []


def test_stalled_thread_keeps_cleanup_prohibited():
    factory = Connections()
    with pytest.raises(RuntimeError, match="stalled threads remain active"):
        _recover_stalled_participants(factory, [Thread(True)], (101, 202))
    assert factory.deleted is False


def test_backend_still_present_keeps_cleanup_prohibited():
    factory = Connections()
    with pytest.raises(RuntimeError, match="stalled backends remain active"):
        _recover_stalled_participants(factory, [Thread()], (101, 202))
    assert factory.deleted is False


def test_recovered_backend_requires_independent_clearance():
    factory = Connections()
    factory.clear_after_cancellation = True
    _recover_stalled_participants(factory, [Thread(), Thread()], (101, 202))
    assert sorted(factory.cancelled) == [101, 202]
    assert factory.deleted is False
