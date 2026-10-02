from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "cloudflare"


def test_worker_resolves_trendcite_from_local_runtime_wheel() -> None:
    data = tomllib.loads((WORKER / "pyproject.toml").read_text(encoding="utf-8"))
    assert "trendcite" in data["project"]["dependencies"]
    source = data["tool"]["uv"]["sources"]["trendcite"]
    assert source == {"path": "wheelhouse/trendcite-0.1.0-py3-none-any.whl"}


def test_worker_uses_canonical_wrangler_config_with_fail_closed_placeholders() -> None:
    text = (WORKER / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"name": "trendcite-cloud-runtime"' in text
    assert '"main": "src/main.py"' in text
    assert '"binding": "HYPERDRIVE"' in text
    assert '"binding": "TREND_QUEUE"' in text
    assert "REPLACE_WITH_NONPROD_HYPERDRIVE_ID" in text
    assert "REPLACE_WITH_NONPROD_QUEUE_NAME" in text
    assert "REPLACE_WITH_NONPROD_DLQ_NAME" in text


def test_packaging_preparer_requires_current_cloud_runtime_modules() -> None:
    text = (ROOT / "scripts" / "prepare_cloudflare_runtime.py").read_text(encoding="utf-8")
    for member in (
        "trendcite/cloud/async_application.py",
        "trendcite/cloud/async_execution.py",
        "trendcite/cloud/async_http.py",
        "trendcite/cloud/async_scheduler.py",
        "trendcite/cloud/async_sources.py",
        "trendcite/cloud/db/postgres.py",
        "trendcite/cloud/db/postgres_execution.py",
    ):
        assert member in text


def test_generated_cloudflare_packaging_artifacts_are_gitignored() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for path in (
        "deploy/cloudflare/wheelhouse/",
        "deploy/cloudflare/python_modules/",
        "deploy/cloudflare/.venv/",
        "deploy/cloudflare/.venv-workers/",
        "deploy/cloudflare/.wrangler/",
        "deploy/cloudflare/uv.lock",
        "deploy/cloudflare/pylock.toml",
    ):
        assert path in text


def test_scheduled_handler_falls_back_to_worker_entrypoint_env() -> None:
    text = (WORKER / "src" / "main.py").read_text(encoding="utf-8")
    assert "runtime_env = env if env is not None else self.env" in text
    assert "result = await _coordinator(runtime_env).plan_and_enqueue(" in text
