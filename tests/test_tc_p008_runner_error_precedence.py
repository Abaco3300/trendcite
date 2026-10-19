"""Offline regression: observer and cleanup failure must both survive."""

import pytest

from trendcite.cloud.tc_p008_hosted_runner import _run_probe_with_injected_connections


def test_multiple_transport_failures_preserve_both_root_causes() -> None:
    attempted: list[int] = []

    def connect() -> None:
        attempted.append(1)
        raise ConnectionError("synthetic transport failure")

    with pytest.raises(RuntimeError, match="observer:ConnectionError,cleanup:ConnectionError"):
        _run_probe_with_injected_connections(connect)
    assert len(attempted) >= 4
