"""Offline fail-closed cancellation response matrix for stalled sessions."""

import pytest

from tests.test_tc_p008_stalled_recovery import Connections, Thread
from trendcite.cloud.tc_p008_hosted_runner import _recover_stalled_participants


@pytest.mark.parametrize("response", [False, None, (), (False,), ("true",)])
def test_unconfirmed_cancel_response_prohibits_cleanup(monkeypatch, response):
    from tests.test_tc_p008_full_offline_runner import Connection

    original = Connection.fetchone

    def fetchone(self):
        if self.kind == "cancel":
            return response
        return original(self)

    monkeypatch.setattr(Connection, "fetchone", fetchone)
    factory = Connections(clear_after_cancellation=True)
    with pytest.raises(RuntimeError, match="cancellation unverified"):
        _recover_stalled_participants(factory, [Thread(), Thread()], (101, 202))
    assert factory.deleted is False


def test_cancel_exception_cannot_be_treated_as_verified(monkeypatch):
    from tests.test_tc_p008_full_offline_runner import Connection

    original = Connection.execute

    def execute(self, sql, params=None):
        if self.kind == "cancel":
            self.factory.cancelled.append(params[0])
            if len(self.factory.cancelled) == 2:
                self.factory.active = False
            raise OSError("synthetic cancel error")
        return original(self, sql, params)

    monkeypatch.setattr(Connection, "execute", execute)
    factory = Connections(clear_after_cancellation=True)
    with pytest.raises(RuntimeError, match="cancellation unverified"):
        _recover_stalled_participants(factory, [Thread(), Thread()], (101, 202))
    assert factory.deleted is False
