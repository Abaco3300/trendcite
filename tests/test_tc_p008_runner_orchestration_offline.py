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

    with pytest.raises(RuntimeError, match="observer:OSError,cleanup:OSError"):
        _run_probe_with_injected_connections(unavailable_connection)

    # Both participants, independent observer, and final cleanup attempted.
    assert len(connection_attempts) >= 4


def test_public_entry_point_still_rejects_all_connections() -> None:
    def forbidden_connection() -> None:
        raise AssertionError("external connection must not happen")

    with pytest.raises(RuntimeError, match="blocked"):
        execute_probe(forbidden_connection, approved=True)
