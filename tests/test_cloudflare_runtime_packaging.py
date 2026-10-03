from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "deploy" / "cloudflare"


def test_worker_resolves_trendcite_from_current_local_runtime_wheel() -> None:
    worker = tomllib.loads((WORKER / "pyproject.toml").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "trendcite" in worker["project"]["dependencies"]
    source = worker["tool"]["uv"]["sources"]["trendcite"]
    version = project["project"]["version"]
    assert source == {"path": f"wheelhouse/trendcite-{version}-py3-none-any.whl"}


def test_worker_uses_canonical_wrangler_config_with_fail_closed_placeholders() -> None:
    text = (WORKER / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"name": "trendcite-cloud-runtime"' in text
    assert '"main": "src/main.py"' in text
    assert '"binding": "HYPERDRIVE"' in text
    assert '"binding": "TREND_QUEUE"' in text
    assert "REPLACE_WITH_NONPROD_HYPERDRIVE_ID" in text
    assert "REPLACE_WITH_NONPROD_QUEUE_NAME" in text
    assert "REPLACE_WITH_NONPROD_DLQ_NAME" in text


def test_packaging_preparer_derives_wheel_version_and_invalidates_vendor_cache() -> None:
    text = (ROOT / "scripts" / "prepare_cloudflare_runtime.py").read_text(encoding="utf-8")
    assert "tomllib.load" in text
    assert 'data.get("project", {}).get("version", "")' in text
    assert 'f"trendcite-{project_version()}-py3-none-any.whl"' in text
    assert "sync_worker_source()" in text
    assert "clear_generated_runtime()" in text
    assert "sync_vendor()" in text
    assert "verify_vendor(EXPECTED_WHEEL)" in text
    assert 'WORKER / "python_modules"' in text
    assert 'WORKER / ".venv-workers"' in text
    assert 'WORKER / "pylock.toml"' in text
    assert "trendcite-0.1.0-py3-none-any.whl" not in text


def test_packaging_preparer_requires_current_cloud_runtime_modules() -> None:
    text = (ROOT / "scripts" / "prepare_cloudflare_runtime.py").read_text(encoding="utf-8")
    for member in (
        "trendcite/cloud/async_application.py",
        "trendcite/cloud/async_delivery.py",
        "trendcite/cloud/async_delivery_service.py",
        "trendcite/cloud/async_execution.py",
        "trendcite/cloud/async_http.py",
        "trendcite/cloud/async_scheduler.py",
        "trendcite/cloud/async_sources.py",
        "trendcite/cloud/db/postgres.py",
        "trendcite/cloud/db/postgres_delivery.py",
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


def test_worker_uses_configured_runtime_role() -> None:
    text = (WORKER / "src" / "main.py").read_text(encoding="utf-8")
    assert 'getattr(env, "TRENDCITE_RUNTIME_ROLE", "trendcite_runtime")' in text
    assert "runtime_role=_runtime_role(env)" in text


def test_worker_delivery_is_explicit_and_fail_closed() -> None:
    text = (WORKER / "src" / "main.py").read_text(encoding="utf-8")
    assert 'getattr(env, "TRENDCITE_DELIVERY_PROVIDER", "")' in text
    assert 'provider != "postmark-nonprod"' in text
    assert 'kind == "deliver_alert"' in text
    assert 'kind == "deliver_digest"' in text
    assert "CloudflarePostTransport" in text


def test_nonprod_wrangler_config_uses_persistent_resources() -> None:
    text = (WORKER / "wrangler.nonprod.jsonc").read_text(encoding="utf-8")
    assert '"name": "trendcite-nonprod-runtime"' in text
    assert '"TRENDCITE_RUNTIME_ROLE": "trendcite_nonprod_runtime"' in text
    assert '"id": "403038608f454b4b8172d9609f6a7383"' in text
    assert '"queue": "trendcite-nonprod-queue"' in text
    assert '"dead_letter_queue": "trendcite-nonprod-dlq"' in text
