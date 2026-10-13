"""Integration readiness must never imply commercial authorization."""

from pathlib import Path

from scripts import check_production_integration_preflight as preflight
from scripts.check_production_integration_preflight import report

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_fails_closed() -> None:
    result = report(ROOT)
    assert result["integration_ready"] is False
    assert result["activation_authorized"] is False
    statuses = {item["code"]: item["status"] for item in result["checks"]}
    assert statuses["DARK_FOUNDATION"] == "PASS"
    assert statuses["HYPERDRIVE_DARK_BINDING_CONFIG"] == "PASS"
    assert statuses["QUEUE_CONNECTION"] == "BLOCKED"
    assert statuses["REMOTE_RESOURCE_DRIFT"] == "NOT_VERIFIED"
    assert statuses["DODO_COMMERCIAL"] == "BLOCKED"
    assert statuses["RETRY_AND_IDEMPOTENCY_EVIDENCE"] == "NOT_VERIFIED"


def test_hyperdrive_dark_binding_drift_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        preflight,
        "python_dark_report",
        lambda root: {"checks": {"only_prod_hyperdrive": False, "state_inactive": True}},
    )
    result = report(ROOT)
    statuses = {item["code"]: item["status"] for item in result["checks"]}
    assert statuses["HYPERDRIVE_DARK_BINDING_CONFIG"] == "BLOCKED"
    assert result["integration_ready"] is False
    assert result["activation_authorized"] is False
