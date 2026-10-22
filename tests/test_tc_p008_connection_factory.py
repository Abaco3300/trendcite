"""No network is allowed while preparing the sandbox connection factory."""

import pytest

from trendcite.cloud.tc_p008_connection_factory import prepare_sandbox_connection

VALID = "postgresql://tc_p008_probe_login@db.btjgozzguhuzfdueensf.supabase.co:5432/postgres"


def test_preparation_performs_zero_driver_calls():
    calls = []

    def driver(**kwargs):
        calls.append(kwargs)
        return object()

    factory = prepare_sandbox_connection(VALID, "synthetic", driver_connect=driver)
    assert calls == []
    factory()
    assert len(calls) == 1
    assert calls[0]["sslmode"] == "verify-full"
    assert calls[0]["connect_timeout"] == 5


def test_invalid_target_rejected_before_driver_call():
    calls = []

    def driver(**kwargs):
        calls.append(kwargs)

    with pytest.raises(RuntimeError, match="dedicated TC-P008 sandbox"):
        prepare_sandbox_connection(
            VALID.replace("db.btjgozzguhuzfdueensf.supabase.co", "localhost"),
            "synthetic",
            driver_connect=driver,
        )
    assert calls == []


def test_non_callable_driver_rejected():
    with pytest.raises(RuntimeError, match="driver unavailable"):
        prepare_sandbox_connection(VALID, "synthetic", driver_connect=None)
