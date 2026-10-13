"""Fail closed on accidental activation of the authorized bound-dark foundation."""

import json
from pathlib import Path

from scripts.check_dark_foundation_readiness import report

ROOT = Path(__file__).resolve().parents[1]


def test_bound_dark_baseline_is_noncommercial() -> None:
    result = report(ROOT)
    assert result["foundation_ready"] is True
    assert result["commercial_ready"] is False


def test_foundation_rejects_unauthorized_bindings_and_routes(tmp_path: Path) -> None:
    source = ROOT / "deploy/cloudflare"
    destination = tmp_path / "deploy/cloudflare"
    destination.mkdir(parents=True)
    for name in ("wrangler.prod.foundation.jsonc", "foundation-dark.js"):
        (destination / name).write_bytes((source / name).read_bytes())
    state = tmp_path / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml"
    state.parent.mkdir(parents=True)
    state.write_bytes((ROOT / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml").read_bytes())
    original = json.loads((destination / "wrangler.prod.foundation.jsonc").read_text())
    for change in (
        {"workers_dev": True},
        {"routes": ["example.invalid/*"]},
        {"triggers": {"crons": ["*/1 * * * *"]}},
        {"queues": {"consumers": [{"queue": "trendcite-prod-queue"}]}},
        {"hyperdrive": [{"binding": "UNEXPECTED", "id": "wrong"}]},
        {"vars": {"TRENDCITE_PRODUCTION_ACTIVATION": "active"}},
    ):
        (destination / "wrangler.prod.foundation.jsonc").write_text(json.dumps(original | change))
        assert report(tmp_path)["foundation_ready"] is False, change
