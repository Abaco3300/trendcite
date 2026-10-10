"""Static contract: dark resources are not commercial or runtime authorization."""

from pathlib import Path

from scripts.check_dark_foundation_readiness import _production_state

ROOT = Path(__file__).resolve().parents[1]


def test_production_boundaries_fail_closed() -> None:
    data = (ROOT / ".irmya/infrastructure/PRODUCTION_RESOURCE_BOUNDARIES.yaml").read_text(
        encoding="utf-8"
    )
    # This checks the canonical inventory's deliberately restricted vocabulary.
    for required in (
        "test_changes: FROZEN",
        "live_changes: FROZEN",
        "live_commercial_status: BLOCKED",
        "brand_id: null",
        "mode: DARK",
        "existence: NOT_CREATED",
        "credential_reference_only: trendcite_prod_hyperdrive_login",
    ):
        assert required in data

    # Independently verify deploy state and fail-closed static runtime contract.
    state = _production_state(ROOT / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml")
    assert state["foundation_only"] == "true"
    assert state["active"] == "false"
    assert state["activation_authorized"] == "false"
    assert state["queues_bound"] == "false"
    assert state["hyperdrive_bound"] == "false"
