"""Fail-closed connection-lifecycle checks using only synthetic sessions."""

import pytest

from tests.test_tc_p008_full_offline_runner import Connection, Connections
from trendcite.cloud.tc_p008_hosted_runner import _run_probe_with_injected_connections


@pytest.mark.parametrize("role", ["observer", "backend", "cleanup", "audit"])
def test_nonparticipant_close_failure_rejects_certification(monkeypatch, role):
    original_close = Connection.close

    def close(self):
        original_close(self)
        if self.kind == role:
            raise OSError("synthetic close failure")

    monkeypatch.setattr(Connection, "close", close)
    factory = Connections()
    factory.active = False
    with pytest.raises((OSError, RuntimeError)):
        _run_probe_with_injected_connections(factory)
    assert role in factory.closed_roles
