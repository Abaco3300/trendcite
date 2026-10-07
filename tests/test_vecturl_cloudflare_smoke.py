from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "deploy" / "cloudflare" / "src" / "main.py"
WRANGLER = ROOT / "deploy" / "cloudflare" / "wrangler.nonprod.jsonc"


def test_vecturl_smoke_is_nonprod_bounded_and_zero_cost() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert 'VECTURL_SMOKE_PATH = "/api/internal/vecturl-runtime-smoke"' in source
    assert 'VECTURL_SMOKE_URL = "https://example.com/"' in source
    assert '"maxCostMicroUsd": 0' in source
    assert '"policyProfile": "best_effort"' in source
    assert 'consumer_id": "trendcite-nonprod"' in source


def test_vecturl_smoke_is_fail_closed_without_temporary_secret() -> None:
    source = MAIN.read_text(encoding="utf-8")
    assert 'getattr(env, "TRENDCITE_VECTURL_SMOKE_TOKEN"' in source
    assert "len(expected) < 32" in source
    assert "hmac.compare_digest" in source
    assert 'error": "not_found"' in source


def test_nonprod_config_pins_vecturl_identity_without_enabling_production() -> None:
    config = json.loads(WRANGLER.read_text(encoding="utf-8"))
    assert config["name"] == "trendcite-nonprod-runtime"
    assert config["vars"]["VECTURL_BASE_URL"] == "https://vecturl.getistriade.com"
    assert config["vars"]["VECTURL_CONSUMER_ID"] == "trendcite-nonprod"
    assert "VECTURL_CONSUMER_TOKEN" not in config["vars"]
    assert "TRENDCITE_VECTURL_SMOKE_TOKEN" not in config["vars"]
