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

    def close(self):
        pass

    def execute(self, query, params):
        if query == "SELECT pg_catalog.pg_stat_clear_snapshot()":
            self.snapshot_resets = getattr(self, "snapshot_resets", 0) + 1
            return self
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


class TransientBackend(Connection):
    """Backend still listed for two reads, then gone (socket close latency)."""

    def __init__(self) -> None:
        super().__init__((1,))
        self.reads = 0

    def fetchone(self):
        self.reads += 1
        return (1,) if self.reads <= 2 else (0,)


def test_transient_backend_listing_is_re_read_with_fresh_snapshot():
    connection = TransientBackend()
    assert independently_verify_backends_terminated(lambda: connection, (123, 456)) is True
    assert connection.reads == 3
    assert connection.snapshot_resets == 3


def test_persistent_backend_polling_is_bounded():
    from trendcite.cloud import tc_p008_hosted_runner as runner

    connection = Connection((1,))
    assert independently_verify_backends_terminated(lambda: connection, (123, 456)) is False
    assert connection.snapshot_resets == runner.BACKEND_EXIT_POLL_ATTEMPTS
