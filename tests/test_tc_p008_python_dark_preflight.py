"""Exercise the offline Python DARK preflight against unsafe drift."""

import json
from pathlib import Path

from scripts.check_python_runtime_dark import report

ROOT = Path(__file__).resolve().parents[1]


def test_dark_runtime_preflight_baseline() -> None:
    result = report(ROOT)
    assert result["dark_ready"] is True
    assert result["commercial_ready"] is False


def test_dark_runtime_preflight_rejects_unsafe_config(tmp_path: Path) -> None:
    source = ROOT / "deploy/cloudflare"
    destination = tmp_path / "deploy/cloudflare"
    destination.mkdir(parents=True)
    for name in ("wrangler.prod.runtime.dark.jsonc", "src/main.py"):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source / name).read_bytes())
    state = tmp_path / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml"
    state.parent.mkdir(parents=True)
    state.write_bytes((ROOT / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml").read_bytes())
    config_path = destination / "wrangler.prod.runtime.dark.jsonc"
    original = json.loads(config_path.read_text())
    for drift in (
        {"workers_dev": True},
        {"routes": ["example.invalid/*"]},
        {"queues": {"consumers": [{"queue": "trendcite-prod-queue"}]}},
        {"vars": {"TRENDCITE_PRODUCTION_ACTIVATION": "enabled"}},
    ):
        config_path.write_text(json.dumps(original | drift))
        assert report(tmp_path)["dark_ready"] is False
