"""Packaged TC-P008 sandbox allowlist and TLS trust-anchor checks (offline)."""

from pathlib import Path

import pytest

from trendcite.cloud.tc_p008_connection_policy import build_secure_connection_kwargs
from trendcite.cloud.tc_p008_sandbox_target import sandbox_dsn, validate_hosted_dsn

POOLER = sandbox_dsn("session-pooler")
DIRECT = sandbox_dsn("direct")
PEM = b"-----BEGIN CERTIFICATE-----\nMIIBsynthetic\n-----END CERTIFICATE-----\n"


def test_runtime_policy_does_not_import_unpackaged_scripts_tree():
    source = Path("src/trendcite/cloud/tc_p008_connection_policy.py").read_text("utf-8")
    assert "from scripts" not in source and "import scripts" not in source


def test_both_allowlisted_transports_resolve_to_the_sandbox_only():
    assert validate_hosted_dsn(DIRECT)["transport"] == "direct"
    pooled = validate_hosted_dsn(POOLER)
    assert pooled["transport"] == "session-pooler"
    assert pooled["user"] == "tc_p008_probe_login.btjgozzguhuzfdueensf"
    assert pooled["role"] == "tc_p008_probe_login"


@pytest.mark.parametrize(
    "dsn",
    [
        POOLER.replace(":5432/", ":6543/"),  # transaction mode multiplexes backends
        POOLER.replace(".btjgozzguhuzfdueensf@", ".yntcafxmjgfjrdinwdmo@"),
        POOLER.replace("tc_p008_probe_login.", "postgres."),
        DIRECT.replace("tc_p008_probe_login@", "tc_p008_probe_login.btjgozzguhuzfdueensf@"),
        POOLER.replace("tc_p008_probe_login.btjgozzguhuzfdueensf@", "tc_p008_probe_login@"),
        POOLER.replace("aws-0-us-east-1", "aws-0-us-west-2"),
    ],
)
def test_cross_wired_or_foreign_targets_rejected(dsn):
    with pytest.raises(RuntimeError, match="dedicated TC-P008 sandbox"):
        validate_hosted_dsn(dsn)


def test_unknown_transport_rejected():
    with pytest.raises(RuntimeError, match="dedicated TC-P008 sandbox"):
        sandbox_dsn("transaction-pooler")


def test_pooler_kwargs_omit_startup_options_but_keep_strict_tls(tmp_path):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(PEM)
    kw = build_secure_connection_kwargs(POOLER, "synthetic", sslrootcert=str(ca))
    assert kw["host"] == "aws-0-us-east-1.pooler.supabase.com"
    assert kw["sslmode"] == "verify-full"
    assert kw["sslrootcert"] == str(ca.resolve())
    assert "options" not in kw


def test_direct_kwargs_keep_timeouts_in_startup_options():
    kw = build_secure_connection_kwargs(DIRECT, "synthetic")
    assert "statement_timeout=8000" in str(kw["options"])


@pytest.mark.parametrize("content", [b"", b"not a certificate"])
def test_non_pem_trust_anchor_rejected(tmp_path, content):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(content)
    with pytest.raises(RuntimeError, match="not PEM"):
        build_secure_connection_kwargs(DIRECT, "synthetic", sslrootcert=str(ca))


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_trust_anchor_rejected(value):
    with pytest.raises(RuntimeError, match="root certificate required"):
        build_secure_connection_kwargs(DIRECT, "synthetic", sslrootcert=value)


def test_missing_trust_anchor_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="unreadable"):
        build_secure_connection_kwargs(
            DIRECT, "synthetic", sslrootcert=str(tmp_path / "absent.crt")
        )
