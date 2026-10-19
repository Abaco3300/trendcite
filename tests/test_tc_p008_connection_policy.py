"""Negative and positive offline checks for TC-P008 connection restrictions."""

import pytest

from trendcite.cloud.tc_p008_connection_policy import build_secure_connection_kwargs

VALID = "postgresql://tc_p008_probe_login@db.btjgozzguhuzfdueensf.supabase.co:5432/postgres"


def test_secure_settings_are_explicit_and_bounded():
    kw = build_secure_connection_kwargs(VALID, "synthetic-not-a-real-secret")
    assert kw["sslmode"] == "verify-full"
    assert kw["connect_timeout"] == 5
    assert kw["host"] == "db.btjgozzguhuzfdueensf.supabase.co"
    assert kw["user"] == "tc_p008_probe_login"
    assert kw["dbname"] == "postgres"
    assert kw["password"] == "synthetic-not-a-real-secret"


@pytest.mark.parametrize(
    "target",
    [
        VALID + "?sslmode=disable",
        VALID + "#host=elsewhere",
        VALID.replace("db.btjgozzguhuzfdueensf.supabase.co", "localhost"),
        VALID.replace("tc_p008_probe_login", "postgres"),
        VALID.replace(":5432/", ":6543/"),
        VALID.replace("/postgres", "/other"),
    ],
)
def test_routing_and_tls_overrides_denied(target):
    with pytest.raises(RuntimeError, match="dedicated TC-P008 sandbox"):
        build_secure_connection_kwargs(target, "synthetic")


@pytest.mark.parametrize("password", ["", "bad\nsecret", "bad\rsecret"])
def test_invalid_secret_rejected(password):
    with pytest.raises(RuntimeError, match="protected sandbox password"):
        build_secure_connection_kwargs(VALID, password)
