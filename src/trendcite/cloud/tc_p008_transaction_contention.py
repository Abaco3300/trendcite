"""Bounded nonprod PostgreSQL transaction-lock contention attestation.

Requires an explicitly supplied authorized connector. Uses transaction-scoped
advisory locks without schema writes. This does not prove unique-key write
contention, Worker termination, or broker ACK-loss recovery.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from typing import Any

Connector = Callable[[], Awaitable[Any]]


async def attest_transaction_lock_contention(connector: Connector) -> dict[str, Any]:
    key = secrets.randbits(62) + (1 << 61)
    held = asyncio.Event()
    checked = asyncio.Event()
    observations: dict[str, Any] = {}

    async def holder() -> None:
        connection = await asyncio.wait_for(connector(), timeout=5)
        try:
            async with connection.transaction():
                observations["holder_pid"] = await connection.fetchval("SELECT pg_backend_pid()")
                await connection.fetchval("SELECT pg_advisory_xact_lock($1)", key)
                held.set()
                await asyncio.wait_for(checked.wait(), timeout=8)
        finally:
            await asyncio.wait_for(connection.close(), timeout=3)

    async def contender() -> None:
        await asyncio.wait_for(held.wait(), timeout=8)
        connection = await asyncio.wait_for(connector(), timeout=5)
        try:
            async with connection.transaction():
                observations["contender_pid"] = await connection.fetchval("SELECT pg_backend_pid()")
                observations["blocked"] = not await connection.fetchval(
                    "SELECT pg_try_advisory_xact_lock($1)", key
                )
                checked.set()
        finally:
            await asyncio.wait_for(connection.close(), timeout=3)

    await asyncio.wait_for(asyncio.gather(holder(), contender()), timeout=16)
    return validate_transaction_observations(observations)


def validate_transaction_observations(observations: dict[str, Any]) -> dict[str, Any]:
    """Classify backend and lock-conflict evidence without network access."""
    if (
        not isinstance(observations.get("holder_pid"), int)
        or not isinstance(observations.get("contender_pid"), int)
        or observations["holder_pid"] <= 0
        or observations["contender_pid"] <= 0
        or observations["holder_pid"] == observations["contender_pid"]
        or observations.get("blocked") is not True
    ):
        raise RuntimeError("distinct hosted PostgreSQL transaction contention not established")
    return {
        "scope": "AUTHORIZED_NONPROD_TRANSACTION_ADVISORY_LOCK",
        "distinct_backends": True,
        "concurrent_transaction_lock_contention": True,
        "unique_key_write_contention": "NOT_VERIFIED",
        "worker_termination": "NOT_VERIFIED",
        "transport_ack_loss": "NOT_VERIFIED",
    }
