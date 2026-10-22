"""End-to-end safety wiring between the prepared factory and the runner gate."""

import pytest

from trendcite.cloud.tc_p008_connection_factory import prepare_sandbox_connection
from trendcite.cloud.tc_p008_hosted_runner import execute_probe

DSN = "postgresql://tc_p008_probe_login@db.btjgozzguhuzfdueensf.supabase.co:5432/postgres"


def test_unapproved_gate_never_invokes_prepared_driver():
    calls = []

    def forbidden_driver(**kwargs):
        calls.append(kwargs)
        raise AssertionError("no live connection authorized")

    factory = prepare_sandbox_connection(DSN, "synthetic-password", driver_connect=forbidden_driver)
    with pytest.raises(RuntimeError, match=r"approval required"):
        execute_probe(factory, approved=False)
    assert calls == []


def test_approved_gate_uses_only_validated_strict_kwargs():
    calls = []

    def refusing_driver(**kwargs):
        calls.append(kwargs)
        raise OSError("synthetic: sandbox unreachable")

    factory = prepare_sandbox_connection(DSN, "synthetic-password", driver_connect=refusing_driver)
    with pytest.raises(RuntimeError, match="cleanup prohibited"):
        execute_probe(factory, approved=True)
    assert calls
    for kwargs in calls:
        assert kwargs["host"] == "db.btjgozzguhuzfdueensf.supabase.co"
        assert kwargs["user"] == "tc_p008_probe_login"
        assert kwargs["sslmode"] == "verify-full"


@pytest.mark.parametrize("secret", [True, 42, object(), None, b"bytes"])
def test_non_string_secrets_rejected_without_leaking(secret):
    with pytest.raises(RuntimeError, match="protected sandbox password"):
        prepare_sandbox_connection(DSN, secret, driver_connect=lambda **kw: None)
