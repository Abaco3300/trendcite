"""The hosted runner never runs without an explicit execution gate."""

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


def test_approved_run_with_unusable_connection_fails_closed_without_cleanup() -> None:
    def unusable_connect() -> None:
        raise OSError("synthetic: sandbox unreachable")

    with pytest.raises(RuntimeError, match="backend identities unverified: cleanup prohibited"):
        execute_probe(unusable_connect, approved=True)


def test_non_callable_factory_rejected() -> None:
    with pytest.raises(RuntimeError, match="connection factory unavailable"):
        execute_probe(None, approved=True)  # type: ignore[arg-type]
