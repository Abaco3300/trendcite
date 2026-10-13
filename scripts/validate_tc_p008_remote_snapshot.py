"""Offline validation of a historical read-only Cloudflare snapshot, not live monitoring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EVIDENCE = ".irmya/evidence/TC-P008-CLOUDFLARE-DARK-SNAPSHOT-2026-10-10.json"


def report(root: Path, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    if snapshot is None:
        snapshot = json.loads((root / EVIDENCE).read_text(encoding="utf-8"))
    worker = snapshot.get("worker", {})
    queue = snapshot.get("queue", {})
    dlq = snapshot.get("dlq", {})
    hyperdrive = snapshot.get("hyperdrive", {})
    checks = {
        "identity": snapshot.get("schema") == "trendcite.tc_p008.cloudflare_dark_snapshot.v1"
        and snapshot.get("account_id") == "a4c8274fca447382525edd54ee20fd74",
        "historical_only": snapshot.get("scope") == "READ_ONLY_HISTORICAL_SNAPSHOT",
        "worker_version": worker.get("name") == "trendcite-prod-runtime"
        and worker.get("version_id") == "b495ea31-8cb5-4c31-a9b9-0e94ca045c7b",
        "subdomain_and_previews_disabled": worker.get("subdomain_enabled") is False
        and worker.get("previews_enabled") is False,
        "no_cron": worker.get("cron_count") == 0,
        "no_route": worker.get("workers_domains_count") == 0
        and worker.get("zones_checked") == worker.get("zones_total")
        and worker.get("zones_checked", 0) > 0
        and worker.get("zone_routes_count") == 0,
        "only_dark_binding": worker.get("bindings")
        == [{"name": "TRENDCITE_PRODUCTION_ACTIVATION", "type": "plain_text"}],
        "queue_unbound": queue.get("id") == "007435e8e7d64f1fb949368f1031e439"
        and queue.get("producers") == 0
        and queue.get("consumers") == 0,
        "dlq_unbound": dlq.get("id") == "8892608637364e92a7e06ca3f7153e19"
        and dlq.get("producers") == 0
        and dlq.get("consumers") == 0,
        "hyperdrive_not_created": hyperdrive.get("prod_name_match_count") == 0,
        "no_activation_authority": snapshot.get("commercial_activation_authorized") is False
        and snapshot.get("customer_activation_authorized") is False,
    }
    return {
        "schema": "trendcite.tc_p008.snapshot_audit.v1",
        "scope": "HISTORICAL_EVIDENCE_ONLY",
        "dark_snapshot_pass": all(checks.values()),
        "live_current_verified": False,
        "customer_ready": False,
        "commercial_ready": False,
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(report(Path(__file__).resolve().parents[1]), indent=2, sort_keys=True))
