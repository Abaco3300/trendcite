"""TC-P008 cancellation failure regression tests using the actual offline runner.

Only synthetic sessions are supplied. A failed or uncertain backend cancellation
must not permit SQL DELETE, even if cancellation SQL returns normally.
"""

import pytest

from tests.test_tc_p008_full_offline_runner import Connection, Connections
from trendcite.cloud.tc_p008_hosted_runner import _run_probe_with_injected_connections


def test_cancel_returns_false_and_backend_remains_visible(monkeypatch):
    original = Connection.execute

    def execute(self, sql, params=None):
        if "pg_cancel_backend" in sql:
            self.factory.cancelled.append(params[0])
            self.result = [(False,)]
            return self
        return original(self, sql, params)

    monkeypatch.setattr(Connection, "execute", execute)
    factory = Connections()

    with pytest.raises(RuntimeError, match="backend cancellation NOT_VERIFIED"):
        _run_probe_with_injected_connections(factory)

    assert sorted(factory.cancelled) == [101, 202]
    assert factory.deleted is False


def test_cancel_raises_and_second_backend_is_still_attempted(monkeypatch):
    original = Connection.execute

    def execute(self, sql, params=None):
        if "pg_cancel_backend" in sql:
            self.factory.cancelled.append(params[0])
            if params[0] == 101:
                raise TimeoutError("synthetic cancel timeout")
            self.result = [(True,)]
            return self
        return original(self, sql, params)

    monkeypatch.setattr(Connection, "execute", execute)
    factory = Connections()

    with pytest.raises(RuntimeError, match="backend cancellation NOT_VERIFIED"):
        _run_probe_with_injected_connections(factory)

    assert sorted(factory.cancelled) == [101, 202]
    assert factory.deleted is False
