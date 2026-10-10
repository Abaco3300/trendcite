"""Integration readiness must never imply commercial authorization."""

from pathlib import Path

from scripts.check_production_integration_preflight import report

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_fails_closed() -> None:
    result = report(ROOT)
    assert result["integration_ready"] is False
    assert result["activation_authorized"] is False
    statuses = {item["code"]: item["status"] for item in result["checks"]}
    assert statuses["DARK_FOUNDATION"] == "PASS"
    assert statuses["HYPERDRIVE_CONNECTION"] == "BLOCKED"
    assert statuses["DODO_COMMERCIAL"] == "BLOCKED"
    assert statuses["RETRY_AND_IDEMPOTENCY_EVIDENCE"] == "NOT_VERIFIED"
