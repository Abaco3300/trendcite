"""Offline fail-closed deployment checks for TrendCite's production Python DARK Worker."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_dark_foundation_readiness import _production_state


def report(root: Path) -> dict:
    config = json.loads((root / "deploy/cloudflare/wrangler.prod.runtime.dark.jsonc").read_text())
    source = (root / "deploy/cloudflare/src/main.py").read_text()
    state = _production_state(root / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml")
    checks = {
        "correct_worker": config.get("name") == "trendcite-prod-runtime",
        "python_entrypoint": config.get("main") == "src/main.py"
        and config.get("compatibility_flags") == ["python_workers"],
        "no_exposure": config.get("workers_dev") is False
        and not config.get("routes")
        and not config.get("route")
        and not config.get("assets")
        and not config.get("triggers")
        and not config.get("queues"),
        "only_prod_hyperdrive": config.get("hyperdrive")
        == [{"binding": "TRENDCITE_PROD_DB", "id": "dae4dcf39acb4b6482bdebbd77fe94d1"}],
        "only_dark_vars": config.get("vars")
        == {
            "TRENDCITE_RUNTIME_ROLE": "trendcite_prod_runtime",
            "TRENDCITE_PRODUCTION_ACTIVATION": "foundation-only",
        },
        "no_secrets": not config.get("secrets"),
        "handlers_guarded": source.count("if _production_foundation_only(") >= 3
        and 'return activation == "foundation-only"' in source
        and 'raise RuntimeError("production foundation is dark")' in source,
        "state_inactive": state.get("active") == "false"
        and state.get("activation_authorized") == "false"
        and state.get("ready") == "false"
        and state.get("foundation_only") == "true"
        and state.get("queues_bound") == "false"
        and state.get("hyperdrive_bound") == "true",
    }
    return {
        "schema": "trendcite.production_python_dark.v1",
        "scope": "LOCAL_STATIC_ONLY",
        "dark_ready": all(checks.values()),
        "production_activated": False,
        "commercial_ready": False,
        "checks": checks,
    }


if __name__ == "__main__":
    result = report(Path(__file__).resolve().parents[1])
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["dark_ready"] else 1)
