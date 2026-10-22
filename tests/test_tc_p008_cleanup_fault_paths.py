"""Scoped cleanup and independent readback failure-injection tests."""

import pytest

from tests.test_tc_p008_full_offline_runner import Connection, Connections
from trendcite.cloud.tc_p008_hosted_runner import _run_probe_with_injected_connections


def test_cleanup_connection_failure_remains_closed(monkeypatch):
    original = Connections.__call__

    def connect(self):
        connection = original(self)
        if connection.kind == "cleanup":
            raise ConnectionError("synthetic cleanup unavailable")
        return connection

    monkeypatch.setattr(Connections, "__call__", connect)
    factory = Connections()
    factory.active = False
    with pytest.raises(RuntimeError, match="cleanup:ConnectionError"):
        _run_probe_with_injected_connections(factory)
    assert factory.deleted is False


def test_independent_readback_failure_never_attests_success(monkeypatch):
    original = Connection.execute

    def execute(self, sql, params=None):
        if self.kind == "audit" and "SELECT count(*)" in sql:
            raise ConnectionError("synthetic audit failure")
        return original(self, sql, params)

    monkeypatch.setattr(Connection, "execute", execute)
    factory = Connections()
    factory.active = False
    with pytest.raises(ConnectionError, match="synthetic audit failure"):
        _run_probe_with_injected_connections(factory)
    assert factory.deleted is True


def test_close_failure_blocks_attestation_despite_zero_residue(monkeypatch):
    original = Connection.close

    def close(self):
        if self.kind == "holder":
            raise OSError("synthetic socket close failed")
        return original(self)

    monkeypatch.setattr(Connection, "close", close)
    factory = Connections()
    factory.active = False
    with pytest.raises(RuntimeError, match="holder:close_failed"):
        _run_probe_with_injected_connections(factory)
    assert factory.deleted is True
