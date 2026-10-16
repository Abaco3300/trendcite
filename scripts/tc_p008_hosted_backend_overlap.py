"""TC-P008: bounded, read-only hosted PostgreSQL backend-overlap attestation.

Invoke explicitly with an authorized nonprod AsyncpgHyperdriveConnector. This
module never resolves credentials, modifies bindings, or runs on import.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

Connector = Callable[[], Awaitable[Any]]

_QUERY = (
    "SELECT pg_backend_pid() AS pid, clock_timestamp() AS started_at, "
    "pg_sleep(1.5), clock_timestamp() AS finished_at"
)


async def attest_hosted_overlap(connector: Connector) -> dict[str, Any]:
    """Collect two independent backend sessions and require observed overlap.

    No durable SQL writes. A failed or sequential run raises instead of PASS.
    """

    async def sample() -> dict[str, Any]:
        connection = await asyncio.wait_for(connector(), timeout=5)
        try:
            result = await asyncio.wait_for(connection.fetchrow(_QUERY), timeout=8)
            if result is None:
                raise RuntimeError("missing PostgreSQL backend sample")
            return {
                "pid": int(result["pid"]),
                "start": result["started_at"],
                "end": result["finished_at"],
            }
        finally:
            await connection.close()

    a, b = await asyncio.wait_for(asyncio.gather(sample(), sample()), timeout=12)
    return validate_backend_samples(a, b)


def validate_backend_samples(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed classification, independently testable without network access."""
    if a["pid"] == b["pid"]:
        raise RuntimeError("two independent PostgreSQL backends not established")
    for record in (a, b):
        if (
            not isinstance(record["start"], datetime)
            or not isinstance(record["end"], datetime)
            or record["start"] >= record["end"]
        ):
            raise RuntimeError("invalid server-side PostgreSQL interval")
    if max(a["start"], b["start"]) >= min(a["end"], b["end"]):
        raise RuntimeError("PostgreSQL backend execution intervals do not overlap")
    return {
        "scope": "HOSTED_NONPROD_ONLY_WHEN_AUTHORIZED_CONNECTOR_SUPPLIED",
        "backends_distinct": True,
        "overlap": True,
        "samples": [
            {"pid": r["pid"], "start": r["start"].isoformat(), "end": r["end"].isoformat()}
            for r in (a, b)
        ],
        "worker_termination": "NOT_VERIFIED",
        "transport_ack_loss": "NOT_VERIFIED",
    }
