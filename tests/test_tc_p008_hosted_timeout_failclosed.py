"""Explicit offline failure injection for incomplete hosted runner.

These tests prove fail-closed gating, not rollback or network recovery.
"""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import (
    execute_probe,
    independently_audit_cleanup,
)


class InjectedFailure:
    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.entered = False

    def __enter__(self) -> "InjectedFailure":
        self.entered = True
        if self.phase == "connect":
            raise TimeoutError("synthetic connection deadline")
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, *_args: object) -> "InjectedFailure":
        if self.phase == "query":
            raise RuntimeError("synthetic statement timeout")
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)


@pytest.mark.parametrize("phase", ["connect", "query"])
def test_injected_audit_failure_cannot_certify(phase: str) -> None:
    connection = InjectedFailure(phase)
    with pytest.raises((TimeoutError, RuntimeError)):
        independently_audit_cleanup(lambda: connection, "test-run", "test-key")


def test_residual_row_is_rejected_after_query() -> None:
    with pytest.raises(RuntimeError, match="audit failed closed"):
        independently_audit_cleanup(lambda: InjectedFailure("residue"), "run", "key")


@pytest.mark.parametrize("approved", [True, False])
def test_no_connection_for_incomplete_runner(approved: bool) -> None:
    def forbidden() -> None:
        raise AssertionError("database connection must not happen")

    with pytest.raises(RuntimeError, match=r"approval required|audit not implemented"):
        execute_probe(forbidden, approved=approved)

