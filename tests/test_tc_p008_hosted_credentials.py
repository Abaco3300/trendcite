"""No credential printing or hosted connections in preflight tests."""

import pytest
from scripts.tc_p008_hosted_preflight import connection_from_environment

TARGET = "postgresql://tc_p008_probe_login@db.btjgozzguhuzfdueensf.supabase.co:5432/postgres"


@pytest.mark.parametrize("bad_password", ["", "line\nfeed", "return\rchar"])
def test_reject_missing_or_multiline_password(
    monkeypatch: pytest.MonkeyPatch, bad_password: str
) -> None:
    monkeypatch.setenv("TC_P008_HOSTED_DSN", TARGET)
    monkeypatch.setenv("TC_P008_HOSTED_PASSWORD", bad_password)
    with pytest.raises(RuntimeError, match="protected sandbox password unavailable"):
        connection_from_environment()


def test_valid_password_not_exposed_in_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TC_P008_HOSTED_DSN", TARGET)
    monkeypatch.setenv("TC_P008_HOSTED_PASSWORD", "ephemeral-test-only")
    metadata, password = connection_from_environment()
    assert metadata["project"] == "btjgozzguhuzfdueensf"
    assert password == "ephemeral-test-only"
    assert "ephemeral-test-only" not in str(metadata)
