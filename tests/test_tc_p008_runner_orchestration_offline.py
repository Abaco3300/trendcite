"""Exercise the actual hosted runner transaction orchestration with offline faults.

Never connects to PostgreSQL, and never bypasses the public execution gate.
"""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import (
    _run_probe_with_injected_connections,
    execute_probe,
)


def test_offline_internal_flow_attempts_cleanup_after_connection_failure() -> None:
    connection_attempts: list[int] = []

    def unavailable_connection() -> None:
        connection_attempts.append(1)
        raise OSError("synthetic offline connection failure")

    with pytest.raises(RuntimeError, match="backend identities unverified: cleanup prohibited"):
        _run_probe_with_injected_connections(unavailable_connection)

    # Both participants, independent observer, and final cleanup attempted.
    assert len(connection_attempts) >= 3


def test_public_entry_point_requires_approval_before_any_connection() -> None:
    attempts: list[int] = []

    def counted_connection() -> None:
        attempts.append(1)
        raise AssertionError("external connection must not happen")

    with pytest.raises(RuntimeError, match="approval required"):
        execute_probe(counted_connection)
    assert attempts == []
