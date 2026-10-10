"""Offline, non-authoritative production integration preflight. Never activates resources."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.check_dark_foundation_readiness import report as dark_report


def report(root: Path) -> dict:
    dark = dark_report(root)
    state = (root / ".irmya/infrastructure/PRODUCTION_RESOURCE_BOUNDARIES.yaml").read_text(
        encoding="utf-8"
    )

    def isolated(resource: str) -> bool:
        section = re.search(rf"(?m)^  {re.escape(resource)}:\n((?:    .*\n)*)", state)
        if section is None:
            return False
        lines = section.group(1).splitlines()
        return "    connected: false" in lines and "    authorized: false" in lines

    checks = [
        {"code": "DARK_FOUNDATION", "status": "PASS" if dark["foundation_ready"] else "BLOCKED"},
        {
            "code": "QUEUE_CONNECTION",
            "status": "BLOCKED" if isolated("queue") and isolated("dlq") else "NOT_VERIFIED",
            "reason": "Production queue and DLQ intentionally unbound",
        },
        {
            "code": "HYPERDRIVE_CONNECTION",
            "status": "BLOCKED"
            if isolated("hyperdrive") and "existence: NOT_CREATED" in state
            else "NOT_VERIFIED",
            "reason": "Credential custody and secure provisioning not authorized",
        },
        {
            "code": "RETRY_AND_IDEMPOTENCY_EVIDENCE",
            "status": "NOT_VERIFIED",
            "reason": "Production-scoped E2E and poison-message evidence required",
        },
        {
            "code": "REMOTE_RESOURCE_DRIFT",
            "status": "NOT_VERIFIED",
            "reason": "Static local scan cannot attest current remote state",
        },
        {
            "code": "CUSTOMER_ACTIVATION",
            "status": "BLOCKED",
            "reason": "Requires separate production Human Gate",
        },
        {
            "code": "DODO_COMMERCIAL",
            "status": "BLOCKED",
            "reason": "Dodo TEST/LIVE frozen; IRCL required",
        },
    ]
    return {
        "schema": "trendcite.production_integration_preflight.v1",
        "scope": "STATIC_NON_AUTHORITATIVE",
        "integration_ready": False,
        "activation_authorized": False,
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(report(Path(__file__).resolve().parents[1]), indent=2))
