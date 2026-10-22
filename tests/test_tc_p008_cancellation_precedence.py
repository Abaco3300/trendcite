"""Cancellation failure must prevent further backend readback or cleanup.

No real connections, credentials or remote SQL are used.
"""

import pytest

from tests.test_tc_p008_stalled_recovery import Connections, Thread
from trendcite.cloud.tc_p008_hosted_runner import _recover_stalled_participants


def test_rejected_cancellations_never_advance_to_readback(monkeypatch):
    from tests.test_tc_p008_full_offline_runner import Connection

    original = Connection.fetchone

    def fetchone(self):
        if self.kind == "cancel":
            return (False,)
        return original(self)

    monkeypatch.setattr(Connection, "fetchone", fetchone)
    factory = Connections(clear_after_cancellation=True)
    with pytest.raises(RuntimeError, match="cancellation unverified"):
        _recover_stalled_participants(factory, [Thread(), Thread()], (101, 202))
    assert factory.calls == 2
    assert factory.deleted is False


def test_cancel_exception_blocks_readback_even_when_sessions_appear_gone(monkeypatch):
    from tests.test_tc_p008_full_offline_runner import Connection

    original = Connection.execute

    def execute(self, sql, params=None):
        if self.kind == "cancel":
            self.factory.cancelled.append(params[0])
            if len(self.factory.cancelled) == 2:
                self.factory.active = False
            raise OSError("synthetic cancellation exception")
        return original(self, sql, params)

    monkeypatch.setattr(Connection, "execute", execute)
    factory = Connections(clear_after_cancellation=True)
    with pytest.raises(RuntimeError, match="cancellation unverified"):
        _recover_stalled_participants(factory, [Thread(), Thread()], (101, 202))
    assert factory.calls == 2
    assert factory.deleted is False
