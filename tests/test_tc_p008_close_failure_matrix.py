"""Lifecycle regression: no session-close failure may become hosted proof.

All connections use offline, injected doubles. No hosted credentials or SQL.
"""

import pytest

from tests.test_tc_p008_full_offline_runner import Connection, Connections
from trendcite.cloud.tc_p008_hosted_runner import _run_probe_with_injected_connections


@pytest.mark.parametrize("role", ("observer", "backend", "cleanup", "audit"))
def test_close_failure_is_never_hosted_success(monkeypatch, role):
    original = Connection.close

    def close(self):
        original(self)
        if self.kind == role:
            raise OSError("synthetic close failure")

    monkeypatch.setattr(Connection, "close", close)
    factory = Connections()
    factory.active = False
    with pytest.raises((OSError, RuntimeError)):
        _run_probe_with_injected_connections(factory)
    assert role in factory.closed_roles


def test_backend_observer_close_failure_blocks_delete(monkeypatch):
    original = Connection.close

    def close(self):
        original(self)
        if self.kind == "backend":
            raise OSError("synthetic backend check close failure")

    monkeypatch.setattr(Connection, "close", close)
    factory = Connections()
    factory.active = False
    with pytest.raises(OSError, match="backend check close failure"):
        _run_probe_with_injected_connections(factory)
    assert factory.deleted is False
