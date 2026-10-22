"""Prove the isolated fault Worker has no automatic delivery entrypoint."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "deploy/cloudflare/tc_p008_fault_worker.wrangler.toml"
MANIFEST = ROOT / "deploy/cloudflare/tc_p008_fault_isolation_manifest.json"


def test_dark_worker_binding_matches_approved_manifest() -> None:
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert set(cfg) == {"name", "main", "compatibility_date", "workers_dev", "vars", "d1_databases"}
    assert cfg["name"] == manifest["name"]
    assert cfg["workers_dev"] is False
    assert cfg["main"] == "tc_p008_fault_worker.mjs"
    assert cfg["vars"] == manifest["vars"]
    assert cfg["d1_databases"] == manifest["d1_databases"]
    assert not any(key in cfg for key in ("queues", "routes", "route", "triggers"))
