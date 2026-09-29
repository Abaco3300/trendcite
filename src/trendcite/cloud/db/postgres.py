"""Async PostgreSQL runtime primitives for TrendCite Cloud.

The OSS/local application remains synchronous and SQLite-backed.  Cloudflare Python
Workers, however, run inside an event loop and E0 validated asyncpg through Hyperdrive.
This module therefore exposes only explicit async boundaries; it deliberately contains
no sync-over-async bridge.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Transaction(Protocol):
    async def __aenter__(self) -> Any: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None: ...


class Connection(Protocol):
    def transaction(self) -> Transaction: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def close(self) -> None: ...


Connector = Callable[[], Awaitable[Connection]]


@dataclass(frozen=True)
class HyperdriveConnectInfo:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_binding(cls, binding: Any) -> HyperdriveConnectInfo:
        required = ("host", "port", "user", "password", "database")
        missing = [name for name in required if not getattr(binding, name, None)]
        if missing:
            raise RuntimeError("invalid Hyperdrive binding: missing " + ", ".join(missing))
        return cls(
            host=str(binding.host),
            port=int(binding.port),
            user=str(binding.user),
            password=str(binding.password),
            database=str(binding.database),
        )


def _safe_role(role: str) -> str:
    if not _IDENTIFIER.fullmatch(role):
        raise ValueError("runtime role must be a PostgreSQL identifier")
    return role


class AsyncpgHyperdriveConnector:
    """Open asyncpg connections using a Cloudflare Hyperdrive binding.

    asyncpg is imported lazily so the zero-dependency OSS core stays importable without
    Cloud runtime dependencies installed.
    """

    def __init__(self, binding: Any) -> None:
        self.info = HyperdriveConnectInfo.from_binding(binding)

    async def __call__(self) -> Connection:
        import asyncpg  # type: ignore[import-not-found]

        return cast(
            Connection,
            await asyncpg.connect(
                host=self.info.host,
                port=self.info.port,
                user=self.info.user,
                password=self.info.password,
                database=self.info.database,
                # Hyperdrive terminates the database transport for the Worker runtime.
                ssl=False,
            ),
        )


class PostgresRuntimeStore:
    """Small async runtime surface proven by E0 and needed by the worker plane.

    This is intentionally not yet a full replacement for SQLiteUnitOfWork.  It owns
    the concurrency-sensitive operations that must be native PostgreSQL statements:
    Queue idempotency and schedule-tick claim/settlement.
    """

    def __init__(self, connector: Connector, *, runtime_role: str = "trendcite_runtime") -> None:
        self._connector = connector
        self._runtime_role = _safe_role(runtime_role)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[Connection]:
        conn: Connection = await self._connector()
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL ROLE {self._runtime_role}")
                yield conn
        finally:
            await conn.close()

    async def healthcheck(self) -> bool:
        conn: Connection = await self._connector()
        try:
            return bool(await conn.fetchval("SELECT 1") == 1)
        finally:
            await conn.close()

    async def record_queue_once(
        self,
        *,
        delivery_id: str,
        workspace_id: str,
        logical_id: str,
        kind: str,
        first_seen_at: datetime,
    ) -> bool:
        """Return True only for the first delivery of a tenant/logical message."""

        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO trendcite.cloud_queue_delivery
                    (delivery_id, workspace_id, logical_id, kind, first_seen_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (workspace_id, logical_id) DO NOTHING
                RETURNING delivery_id
                """,
                delivery_id,
                workspace_id,
                logical_id,
                kind,
                first_seen_at.isoformat(),
            )
            return row is not None

    async def claim_tick(
        self,
        *,
        workspace_id: str,
        tick_id: str,
        owner: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        """Atomically claim one pending/retryable/expired tick."""

        now_text = now.isoformat()
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                UPDATE trendcite.cloud_schedule_tick
                SET status='running',
                    attempt=attempt+1,
                    lease_owner=$1,
                    lease_expires_at=$2,
                    error_code='',
                    error_detail='',
                    updated_at=$3,
                    started_at=$3,
                    finished_at=NULL
                WHERE workspace_id=$4
                  AND tick_id=$5
                  AND (
                       status='pending'
                    OR (status='failed' AND attempt<max_attempts)
                    OR (
                        status='running'
                        AND (lease_expires_at IS NULL OR lease_expires_at<=$3)
                    )
                  )
                RETURNING tick_id
                """,
                owner,
                lease_expires_at.isoformat(),
                now_text,
                workspace_id,
                tick_id,
            )
            return row is not None

    async def settle_tick(
        self,
        *,
        workspace_id: str,
        tick_id: str,
        expected_owner: str,
        status: str,
        attempt: int,
        run_id: str,
        skip_reason: str,
        error_code: str,
        error_detail: str,
        updated_at: datetime,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> bool:
        """Settle only while this caller still owns the lease."""

        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                UPDATE trendcite.cloud_schedule_tick
                SET status=$1,
                    attempt=$2,
                    lease_owner='',
                    lease_expires_at=NULL,
                    run_id=$3,
                    skip_reason=$4,
                    error_code=$5,
                    error_detail=$6,
                    updated_at=$7,
                    started_at=$8,
                    finished_at=$9
                WHERE workspace_id=$10
                  AND tick_id=$11
                  AND lease_owner=$12
                RETURNING tick_id
                """,
                status,
                attempt,
                run_id,
                skip_reason,
                error_code,
                error_detail,
                updated_at.isoformat(),
                None if started_at is None else started_at.isoformat(),
                None if finished_at is None else finished_at.isoformat(),
                workspace_id,
                tick_id,
                expected_owner,
            )
            return row is not None


def postgres_migration_batches(sql_files: list[str]) -> list[str]:
    """Wrap portable Cloud SQL migrations for administrative PostgreSQL execution.

    The Worker must never call this function.  The caller is an admin/deployment path
    that owns CREATE/ALTER authority; runtime roles should not.
    """

    prefix = "CREATE SCHEMA IF NOT EXISTS trendcite;\nSET search_path TO trendcite, pg_catalog;\n"
    return [prefix + sql for sql in sql_files]
