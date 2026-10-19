"""End-to-end safety wiring: the public runner never invokes the driver."""

import pytest

from trendcite.cloud.tc_p008_connection_factory import prepare_sandbox_connection
from trendcite.cloud.tc_p008_hosted_runner import execute_probe

DSN = "postgresql://tc_p008_probe_login@db.btjgozzguhuzfdueensf.supabase.co:5432/postgres"


@pytest.mark.parametrize("approved", [False, True])
def test_public_gate_never_invokes_prepared_driver(approved):
    calls = []

    def forbidden_driver(**kwargs):
        calls.append(kwargs)
        raise AssertionError("no live connection authorized")

    factory = prepare_sandbox_connection(DSN, "synthetic-password", driver_connect=forbidden_driver)
    with pytest.raises(RuntimeError, match=r"approval required|hosted runner blocked"):
        execute_probe(factory, approved=approved)
    assert calls == []


@pytest.mark.parametrize("secret", [True, 42, object(), None, b"bytes"])
def test_non_string_secrets_rejected_without_leaking(secret):
    with pytest.raises(RuntimeError, match="protected sandbox password"):
        prepare_sandbox_connection(DSN, secret, driver_connect=lambda **kw: None)
