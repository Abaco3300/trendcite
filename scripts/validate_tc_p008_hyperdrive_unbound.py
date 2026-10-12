"""Fail-closed static attestation of a created-but-unbound Hyperdrive.

The attestation is documentary, never a live database connectivity test.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_dark_foundation_readiness import _production_state
from scripts.check_dark_foundation_readiness import report as dark_report


def report(root: Path) -> dict:
    state = _production_state(root / ".irmya/infrastructure/DEPLOYMENT_STATE.yaml")
    dark = dark_report(root)
    expected = {
        "hyperdrive_status": "CREATED_UNBOUND",
        "hyperdrive_name": "trendcite-prod-hyperdrive",
        "hyperdrive_id": "dae4dcf39acb4b6482bdebbd77fe94d1",
        "hyperdrive_origin_host": "db.yntcafxmjgfjrdinwdmo.supabase.co",
        "hyperdrive_origin_port": "5432",
        "hyperdrive_origin_database": "postgres",
        "hyperdrive_origin_user": "trendcite_prod_hyperdrive_login",
        "hyperdrive_sslmode": "verify-full",
        "hyperdrive_ca_certificate_id": "42488d5e-25c1-42dc-971e-b44cfefca64f",
        "hyperdrive_caching_disabled": "true",
        "hyperdrive_origin_connection_limit": "5",
    }
    checks = {key: state.get(key) == val for key, val in expected.items()}
    checks["dark_foundation_local_static"] = dark["foundation_ready"] is True
    return {
        "schema": "trendcite.tc_p008.hyperdrive_unbound_attestation.v1",
        "scope": "LOCAL_STATIC_ONLY",
        "configuration_attested": all(checks.values()),
        "live_sql_verified": False,
        "production_runtime_authorized": False,
        "commercial_ready": False,
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(report(Path(__file__).resolve().parents[1]), indent=2, sort_keys=True))
