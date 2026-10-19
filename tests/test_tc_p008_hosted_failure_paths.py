"""Injected failure tests: hosted runner must fail closed with no connections."""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import (
    execute_probe,
    independently_audit_cleanup,
)


class BrokenConnection:
    def __enter__(self) -> "BrokenConnection":
        raise OSError("synthetic connection failure")

    def close(self) -> None:
        pass

    def __exit__(self, *_args: object) -> None:
        pass


class BrokenQuery:
    def __enter__(self) -> "BrokenQuery":
        return self

    def close(self) -> None:
        pass

    def __exit__(self, *_args: object) -> None:
        pass

    def execute(self, *_args: object) -> None:
        raise RuntimeError("synthetic SQL failure")


def test_execution_denied_even_when_approved() -> None:
    connections: list[bool] = []

    def connect() -> BrokenConnection:
        connections.append(True)
        return BrokenConnection()

    with pytest.raises(RuntimeError, match="independent cleanup audit not implemented"):
        execute_probe(connect, approved=True)
    assert connections == []


@pytest.mark.parametrize("connect", [BrokenConnection, BrokenQuery])
def test_cleanup_audit_connection_or_sql_failure_fails_closed(connect: type) -> None:
    with pytest.raises((OSError, RuntimeError)):
        independently_audit_cleanup(connect, "synthetic-run", "synthetic-key")
