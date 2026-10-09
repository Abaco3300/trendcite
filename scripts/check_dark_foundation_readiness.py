"""Offline checks for the disconnected production foundation, not commercial readiness."""

from __future__ import annotations

import json
from pathlib import Path


def _production_state(path: Path) -> dict[str, str]:
    """Read only flat production scalar fields, with no external YAML dependency."""
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    try:
        start = lines.index("production:")
    except ValueError:
        return {}
    state: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if line and not line[0].isspace():
            break
        if line.startswith("  ") and ":" in line:
            key, value = line.strip().split(":", 1)
            state[key] = value.strip()
    return state


def report(root: Path) -> dict:
    config_path = root / "deploy/cloudflare/wrangler.prod.foundation.jsonc"
    worker_path = root / "deploy/cloudflare/foundation-dark.js"
    state_path = root / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = worker_path.read_text(encoding="utf-8")
    state = _production_state(state_path)
    checks = {
        "foundation_entrypoint": config.get("main") == "foundation-dark.js",
        "production_name": config.get("name") == "trendcite-prod-runtime",
        "workers_dev_disabled": config.get("workers_dev") is False,
        "foundation_flag": config.get("vars", {}).get("TRENDCITE_PRODUCTION_ACTIVATION")
        == "foundation-only",
        "no_routes": not config.get("routes") and not config.get("route"),
        "no_cron": not config.get("triggers"),
        "no_queue_bindings": not config.get("queues"),
        "no_hyperdrive": not config.get("hyperdrive"),
        "no_secrets_in_config": not config.get("secrets"),
        "no_customer_imports": "import " not in source,
        "http_rejects": "status: 404" in source,
        "queue_rejects": 'throw new Error("production foundation is dark")' in source,
        "schedule_noop": "async scheduled()" in source and "return;" in source,
        "state_is_dark": state.get("foundation_status") == "DEPLOYED_DARK"
        and state.get("foundation_only") == "true",
        "state_not_active": state.get("active") == "false"
        and state.get("activation_authorized") == "false"
        and state.get("ready") == "false",
        "state_unbound": state.get("queues_bound") == "false"
        and state.get("hyperdrive_bound") == "false",
    }
    return {
        "schema": "trendcite.dark_foundation_readiness.v1",
        "scope": "LOCAL_STATIC_ONLY",
        "foundation_ready": all(checks.values()),
        "commercial_ready": False,
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(report(Path(__file__).resolve().parents[1]), indent=2, sort_keys=True))
