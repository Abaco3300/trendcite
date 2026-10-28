"""Unit tests for independent hosted cleanup audit; no network calls."""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import independently_audit_cleanup


class FakeSession:
    def __init__(self, value: object) -> None:
        self.value = value
        self.params: tuple[str, str] | None = None

    def __enter__(self) -> "FakeSession":
        return self

    def close(self) -> None:
        pass

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[str, str]) -> "FakeSession":
        assert "WHERE probe_run=%s AND probe_key=%s" in sql
        self.params = params
        return self

    def fetchone(self) -> object:
        return self.value


def test_independent_readback_scoped_to_run_and_key() -> None:
    session = FakeSession((0,))
    assert independently_audit_cleanup(lambda: session, "run-a", "key-b") == 0
    assert session.params == ("run-a", "key-b")


@pytest.mark.parametrize("record", [(1,), (False,), ("0",), None, (), (0, 0)])
def test_invalid_readback_fails_closed(record: object) -> None:
    with pytest.raises(RuntimeError, match="cleanup audit"):
        independently_audit_cleanup(lambda: FakeSession(record), "run", "key")


def test_missing_identifier_denied() -> None:
    with pytest.raises(RuntimeError, match="identifiers"):
        independently_audit_cleanup(lambda: None, "", "key")
