"""Repository-only, fail-closed production readiness audit."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def report(root: Path) -> dict[str, Any]:
    worker = root / "deploy" / "cloudflare"
    canonical = _text(worker / "wrangler.jsonc")
    foundation = _text(worker / "wrangler.prod.foundation.jsonc")
    runtime = _text(worker / "src" / "main.py")
    customer = _text(root / "src" / "trendcite" / "cloud" / "customer_api.py")

    findings: list[dict[str, str]] = []

    def add(code: str, blocked: bool, detail: str) -> None:
        findings.append(
            {"code": code, "status": "BLOCKER" if blocked else "PASS", "detail": detail}
        )

    add(
        "PROD_CANONICAL_CONFIG_PLACEHOLDERS",
        "REPLACE_WITH_" in canonical,
        "Canonical Wrangler config still has unresolved resource placeholders.",
    )
    add(
        "PROD_FOUNDATION_DARK",
        not (
            '"workers_dev": false' in foundation
            and '"TRENDCITE_PRODUCTION_ACTIVATION": "foundation-only"' in foundation
        ),
        "Production foundation must remain dark and explicitly gated.",
    )
    add(
        "PROD_HYPERDRIVE_UNBOUND",
        '"hyperdrive"' not in foundation,
        "Production Hyperdrive is not yet bound to the dark foundation.",
    )
    add(
        "PROD_QUEUE_UNBOUND",
        '"queues"' not in foundation,
        "Production Queue/DLQ exist but are intentionally not bound to the Worker.",
    )
    add(
        "PROD_FEATURES_NOT_AUTHORIZED",
        (
            'flag == "nonprod-enabled"' in runtime
            and "MUTATIONS_ENABLED_VALUE" in customer
            and '"nonprod" in role' in customer
            and 'provider != "postmark-nonprod"' in runtime
        ),
        "Mutations, entitlements, automation, delivery and VectURL remain nonprod-only.",
    )
    add(
        "PROD_DARK_RUNTIME_GUARD",
        "def _production_foundation_only" not in runtime,
        "Worker must reject execution while foundation-only.",
    )

    blockers = [item for item in findings if item["status"] == "BLOCKER"]
    return {
        "schema": "trendcite.production_readiness.v1",
        "ready": not blockers,
        "blocker_count": len(blockers),
        "findings": findings,
    }


if __name__ == "__main__":
    import json

    root = Path(__file__).resolve().parents[1]
    print(json.dumps(report(root), indent=2, sort_keys=True))
