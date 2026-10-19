"""Independent backend check uses a separate injected observer, never network."""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import independently_verify_backends_terminated


class Connection:
    def __init__(self, response: object) -> None:
        self.response = response
        self.arguments = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query, params):
        assert "pg_catalog.pg_stat_activity" in query
        assert "pid = ANY(%s)" in query
        self.arguments = params
        return self

    def fetchone(self):
        return self.response


@pytest.mark.parametrize(("remaining", "expected"), [(0, True), (1, False), (2, False)])
def test_backend_evidence_is_independent_and_exact(remaining: int, expected: bool):
    connection = Connection((remaining,))
    assert independently_verify_backends_terminated(lambda: connection, (123, 456)) is expected
    assert connection.arguments == ([123, 456],)


@pytest.mark.parametrize("bad", [(0, 2), (1, 1), (-1, 2), ("1", 2), (True, 3)])
def test_invalid_pids_fail_closed(bad):
    with pytest.raises(RuntimeError, match="invalid PostgreSQL backend"):
        independently_verify_backends_terminated(lambda: None, bad)


@pytest.mark.parametrize("bad", [None, (), (True,), ("0",)])
def test_invalid_observer_evidence_fail_closed(bad):
    with pytest.raises(RuntimeError, match="termination evidence malformed"):
        independently_verify_backends_terminated(lambda: Connection(bad), (123, 456))
