"""Fail-closed regressions for DARK Worker source and declared production state."""

from pathlib import Path

from scripts.check_dark_foundation_readiness import report

ROOT = Path(__file__).resolve().parents[1]


def test_source_or_state_drift_does_not_count_as_dark(tmp_path: Path) -> None:
    original_worker = (ROOT / "deploy/cloudflare/foundation-dark.js").read_text()
    original_state = (ROOT / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml").read_text()
    config = tmp_path / "deploy/cloudflare/wrangler.prod.foundation.jsonc"
    config.parent.mkdir(parents=True)
    config.write_bytes((ROOT / "deploy/cloudflare/wrangler.prod.foundation.jsonc").read_bytes())
    worker = config.parent / "foundation-dark.js"
    state = tmp_path / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml"
    state.parent.mkdir(parents=True)
    for worker_text, state_text in (
        (original_worker.replace("status: 404", "status: 200"), original_state),
        (
            original_worker.replace('throw new Error("production foundation is dark")', "return;"),
            original_state,
        ),
        (original_worker, original_state.replace("active: false", "active: true")),
        (
            original_worker,
            original_state.replace("hyperdrive_bound: true", "hyperdrive_bound: false"),
        ),
        (original_worker, original_state.replace("queues_bound: false", "queues_bound: true")),
    ):
        worker.write_text(worker_text)
        state.write_text(state_text)
        assert report(tmp_path)["foundation_ready"] is False
