"""Fail-closed preflight for a Python runtime deployed without activation."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy/cloudflare/wrangler.prod.runtime.dark.jsonc"
MAIN = ROOT / "deploy/cloudflare/src/main.py"


def test_dark_python_runtime_has_no_public_or_job_targets() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["name"] == "trendcite-prod-runtime"
    assert config["main"] == "src/main.py"
    assert config["workers_dev"] is False
    assert config["compatibility_flags"] == ["python_workers"]
    assert config.get("routes") is None
    assert config.get("assets") is None
    assert config.get("triggers") is None
    assert config.get("queues") is None
    assert config["vars"] == {
        "TRENDCITE_RUNTIME_ROLE": "trendcite_prod_runtime",
        "TRENDCITE_PRODUCTION_ACTIVATION": "foundation-only",
    }
    assert config["hyperdrive"] == [
        {
            "binding": "TRENDCITE_PROD_DB",
            "id": "dae4dcf39acb4b6482bdebbd77fe94d1",
        }
    ]


def test_python_runtime_guards_all_event_handlers_before_work() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert 'return activation == "foundation-only"' in source
    assert 'if "prod" not in role or "nonprod" in role:' in source
    assert "async def fetch(self, request:" in source
    assert "async def queue(self, batch:" in source
    assert "async def scheduled(self, controller:" in source
    fetch = source.split("async def fetch(self, request:", 1)[1].split(
        "async def queue(self, batch:", 1
    )[0]
    queue = source.split("async def queue(self, batch:", 1)[1].split(
        "async def scheduled(self, controller:", 1
    )[0]
    scheduled = source.split("async def scheduled(self, controller:", 1)[1]
    assert "if _production_foundation_only(self.env):" in fetch
    assert "if _production_foundation_only(runtime_env):" in queue
    assert "if _production_foundation_only(runtime_env):" in scheduled
    assert fetch.index("if _production_foundation_only(self.env):") < fetch.index(
        "path = urlparse("
    )
    assert queue.index("if _production_foundation_only(runtime_env):") < queue.index(
        "store = _store("
    )
    assert scheduled.index("if _production_foundation_only(runtime_env):") < scheduled.index(
        "now = datetime.now("
    )
    assert 'return Response.json({"ok": False, "error": "not_found"}, status=404)' in source
    assert 'raise RuntimeError("production foundation is dark")' in source
