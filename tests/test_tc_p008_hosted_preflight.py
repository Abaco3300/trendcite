"""Hosted sandbox target checks must fail before network or SQL."""

import pytest
from scripts.tc_p008_hosted_preflight import validate_hosted_dsn

GOOD = "postgresql://tc_p008_probe_login@db.btjgozzguhuzfdueensf.supabase.co:5432/postgres"


def test_sandbox_target() -> None:
    assert validate_hosted_dsn(GOOD)["project"] == "btjgozzguhuzfdueensf"


@pytest.mark.parametrize(
    "dsn",
    [
        GOOD + "?host=db.yntcafxmjgfjrdinwdmo.supabase.co",
        GOOD + "?dbname=production",
        GOOD + "?hostaddr=203.0.113.1",
        GOOD + "#fragment",
        GOOD.replace("postgresql:", "postgres:"),
        GOOD.replace("btjgozzguhuzfdueensf", "yntcafxmjgfjrdinwdmo"),
        GOOD.replace("tc_p008_probe_login", "postgres"),
        GOOD.replace(":5432", ":5433"),
        GOOD.replace("/postgres", "/production"),
        GOOD.replace("@", ":embeddedsecret@"),
        "host=db.btjgozzguhuzfdueensf.supabase.co dbname=postgres",
    ],
)
def test_reject_non_sandbox(dsn: str) -> None:
    with pytest.raises(RuntimeError, match="sandbox target"):
        validate_hosted_dsn(dsn)
