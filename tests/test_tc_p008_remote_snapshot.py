"""Fail-closed validation for captured provider metadata, not live authorization."""

import json
from copy import deepcopy
from pathlib import Path

from scripts.validate_tc_p008_remote_snapshot import EVIDENCE, report

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / EVIDENCE).read_text(encoding="utf-8"))


def test_snapshot_dark_pass_but_never_authorizes_activation() -> None:
    result = report(ROOT)
    assert result["dark_snapshot_pass"] is True
    assert result["live_current_verified"] is False
    assert result["customer_ready"] is False
    assert result["commercial_ready"] is False
    assert all(result["checks"].values())


def test_dark_snapshot_detects_resource_drift() -> None:
    mutations = [
        ("worker", "cron_count", 1),
        ("worker", "zone_routes_count", 1),
        ("worker", "subdomain_enabled", True),
        ("worker", "bindings", [{"name": "HYPERDRIVE", "type": "hyperdrive"}]),
        ("queue", "consumers", 1),
        ("queue", "producers", 1),
        ("dlq", "consumers", 1),
        ("hyperdrive", "prod_name_match_count", 1),
    ]
    for section, key, value in mutations:
        snapshot = deepcopy(BASE)
        snapshot[section][key] = value
        assert report(ROOT, snapshot)["dark_snapshot_pass"] is False, (section, key)
