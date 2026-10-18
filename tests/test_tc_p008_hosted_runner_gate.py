"""The hosted runner is non-executable without an explicit execution gate."""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import execute_probe


def test_default_denial_never_calls_connection_factory() -> None:
    invoked = []

    def forbidden_connect() -> None:
        invoked.append(True)
        raise AssertionError("network attempted")

    with pytest.raises(RuntimeError, match="explicit hosted probe approval"):
        execute_probe(forbidden_connect)
    assert not invoked


def test_false_approval_denied() -> None:
    with pytest.raises(RuntimeError, match="explicit hosted probe approval"):
        execute_probe(lambda: None, approved=False)


def test_approval_does_not_bypass_incomplete_audit() -> None:
    def forbidden_connect() -> None:
        raise AssertionError("network attempted")

    with pytest.raises(RuntimeError, match="independent cleanup audit"):
        execute_probe(forbidden_connect, approved=True)
