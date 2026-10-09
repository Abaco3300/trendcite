"""Guard against accidental activation of the dark production foundation."""

from pathlib import Path

from scripts.check_dark_foundation_readiness import report

ROOT = Path(__file__).resolve().parents[1]


def test_dark_foundation_static_readiness() -> None:
    result = report(ROOT)
    assert result["foundation_ready"] is True
    assert result["commercial_ready"] is False
    assert all(result["checks"].values())


def test_dark_foundation_mutation_is_rejected(tmp_path: Path) -> None:
    import json
    import shutil

    source = ROOT / "deploy/cloudflare"
    dest = tmp_path / "deploy/cloudflare"
    dest.mkdir(parents=True)
    shutil.copyfile(source / "foundation-dark.js", dest / "foundation-dark.js")
    config = json.loads((source / "wrangler.prod.foundation.jsonc").read_text(encoding="utf-8"))
    config["queues"] = {"producers": [{"binding": "JOBS_QUEUE", "queue": "trendcite-prod-queue"}]}
    (dest / "wrangler.prod.foundation.jsonc").write_text(json.dumps(config), encoding="utf-8")
    state_dest = tmp_path / ".irmya/infrastructure"
    state_dest.mkdir(parents=True)
    shutil.copyfile(
        ROOT / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml", state_dest / "DEPLOYMENT_STATE.yaml"
    )
    result = report(tmp_path)
    assert result["foundation_ready"] is False
    assert result["checks"]["no_queue_bindings"] is False
