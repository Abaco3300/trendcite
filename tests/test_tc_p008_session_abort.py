"""Synthetic lifecycle failures without PostgreSQL connections."""

import pytest

from trendcite.cloud.tc_p008_session_abort import abort_session


class Session:
    def __init__(self, fail: str = "") -> None:
        self.fail = fail
        self.calls: list[str] = []

    def rollback(self) -> None:
        self.calls.append("rollback")
        if self.fail == "rollback":
            raise RuntimeError("injected")

    def close(self) -> None:
        self.calls.append("close")
        if self.fail == "close":
            raise RuntimeError("injected")


def test_rollback_precedes_close() -> None:
    session = Session()
    abort_session(session)
    assert session.calls == ["rollback", "close"]


@pytest.mark.parametrize("failure", ["rollback", "close"])
def test_failure_does_not_skip_other_operation(failure: str) -> None:
    session = Session(failure)
    with pytest.raises(RuntimeError, match="abort incomplete"):
        abort_session(session)
    assert session.calls == ["rollback", "close"]


def test_missing_methods_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="rollback_unavailable,close_unavailable"):
        abort_session(object())
