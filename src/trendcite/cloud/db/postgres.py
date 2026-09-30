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

from ..domain.radar import RadarRun
from ..domain.scheduling import (
    SKIP_CATCH_UP_EXCEEDED,
    DuePlan,
    RadarSchedule,
    ScheduleTick,
)

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
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
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

    async def get_or_create_run(
        self,
        *,
        workspace_id: str,
        radar_id: str,
        evaluation_cutoff: datetime,
        started_at: datetime,
    ) -> RadarRun:
        async with self._transaction() as conn:
            version_id = await conn.fetchval(
                """
                SELECT version_id
                FROM trendcite.cloud_radar_version
                WHERE workspace_id=$1 AND radar_id=$2
                ORDER BY version_number DESC
                LIMIT 1
                """,
                workspace_id,
                radar_id,
            )
            if not version_id:
                raise RuntimeError("radar has no version in workspace")
            candidate = RadarRun.create(
                workspace_id=workspace_id,
                radar_id=radar_id,
                radar_version_id=str(version_id),
                evaluation_cutoff=evaluation_cutoff,
                started_at=started_at,
            )
            await conn.execute(
                """
                INSERT INTO trendcite.cloud_radar_run
                    (run_id, workspace_id, radar_id, radar_version_id,
                     evaluation_cutoff, idempotency_key, status, coverage_state,
                     attempt, signal_count, match_count, error_code, error_detail,
                     started_at, finished_at)
                VALUES
                    ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (workspace_id, idempotency_key) DO NOTHING
                """,
                candidate.run_id,
                candidate.workspace_id,
                candidate.radar_id,
                candidate.radar_version_id,
                candidate.evaluation_cutoff.isoformat(),
                candidate.idempotency_key,
                candidate.status,
                candidate.coverage_state,
                candidate.attempt,
                candidate.signal_count,
                candidate.match_count,
                candidate.error_code,
                candidate.error_detail,
                candidate.started_at.isoformat(),
                None,
            )
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_radar_run
                WHERE workspace_id=$1 AND idempotency_key=$2
                """,
                workspace_id,
                candidate.idempotency_key,
            )
            if row is None:
                raise RuntimeError("radar run insert was not observable")
            return _run(row)

    async def get_run(self, workspace_id: str, run_id: str) -> RadarRun | None:
        conn: Connection = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_radar_run
                WHERE workspace_id=$1 AND run_id=$2
                """,
                workspace_id,
                run_id,
            )
            return None if row is None else _run(row)
        finally:
            await conn.close()

    async def update_run(self, run: RadarRun) -> None:
        async with self._transaction() as conn:
            status = await conn.execute(
                """
                UPDATE trendcite.cloud_radar_run
                SET status=$1,
                    coverage_state=$2,
                    attempt=$3,
                    signal_count=$4,
                    match_count=$5,
                    error_code=$6,
                    error_detail=$7,
                    started_at=$8,
                    finished_at=$9
                WHERE workspace_id=$10 AND run_id=$11
                """,
                run.status,
                run.coverage_state,
                run.attempt,
                run.signal_count,
                run.match_count,
                run.error_code,
                run.error_detail,
                run.started_at.isoformat(),
                None if run.finished_at is None else run.finished_at.isoformat(),
                run.workspace_id,
                run.run_id,
            )
            if status.endswith(" 0"):
                raise RuntimeError("radar run update matched no row")

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

    async def list_enabled_schedules(self) -> tuple[RadarSchedule, ...]:
        conn: Connection = await self._connector()
        try:
            rows = await conn.fetch(
                """
                SELECT schedule_id, workspace_id, radar_id, enabled, cadence,
                       utc_offset_minutes, anchor_at, max_catch_up, lease_seconds,
                       max_attempts, cadence_version, created_at, updated_at,
                       last_planned_at
                FROM trendcite.cloud_radar_schedule
                WHERE enabled=1
                ORDER BY COALESCE(last_planned_at, anchor_at), schedule_id
                """
            )
            return tuple(_schedule(row) for row in rows)
        finally:
            await conn.close()

    async def persist_plan(
        self,
        schedule: RadarSchedule,
        plan: DuePlan,
        *,
        now: datetime,
    ) -> tuple[ScheduleTick, ...]:
        created: list[ScheduleTick] = []
        async with self._transaction() as conn:
            for cutoff in plan.skipped:
                tick = ScheduleTick.create(
                    schedule=schedule,
                    evaluation_cutoff=cutoff,
                    created_at=now,
                    status="skipped",
                    skip_reason=SKIP_CATCH_UP_EXCEEDED,
                )
                await _insert_tick(conn, tick)
            for cutoff in plan.due:
                tick = ScheduleTick.create(
                    schedule=schedule,
                    evaluation_cutoff=cutoff,
                    created_at=now,
                )
                row = await _insert_tick(conn, tick)
                if row is not None:
                    created.append(tick)
            if plan.watermark is not None:
                await conn.execute(
                    """
                    UPDATE trendcite.cloud_radar_schedule
                    SET last_planned_at=$1
                    WHERE workspace_id=$2
                      AND schedule_id=$3
                      AND (last_planned_at IS NULL OR last_planned_at<$1)
                    """,
                    plan.watermark.isoformat(),
                    schedule.workspace_id,
                    schedule.schedule_id,
                )
        return tuple(created)

    async def get_schedule(self, workspace_id: str, schedule_id: str) -> RadarSchedule | None:
        conn: Connection = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT schedule_id, workspace_id, radar_id, enabled, cadence,
                       utc_offset_minutes, anchor_at, max_catch_up, lease_seconds,
                       max_attempts, cadence_version, created_at, updated_at,
                       last_planned_at
                FROM trendcite.cloud_radar_schedule
                WHERE workspace_id=$1 AND schedule_id=$2
                """,
                workspace_id,
                schedule_id,
            )
            return None if row is None else _schedule(row)
        finally:
            await conn.close()

    async def get_tick(self, workspace_id: str, tick_id: str) -> ScheduleTick | None:
        conn: Connection = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_schedule_tick
                WHERE workspace_id=$1 AND tick_id=$2
                """,
                workspace_id,
                tick_id,
            )
            return None if row is None else _tick(row)
        finally:
            await conn.close()

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
        tick: ScheduleTick,
        *,
        expected_owner: str,
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
                tick.status,
                tick.attempt,
                tick.run_id,
                tick.skip_reason,
                tick.error_code,
                tick.error_detail,
                tick.updated_at.isoformat(),
                None if tick.started_at is None else tick.started_at.isoformat(),
                None if tick.finished_at is None else tick.finished_at.isoformat(),
                tick.workspace_id,
                tick.tick_id,
                expected_owner,
            )
            return row is not None


async def _insert_tick(conn: Connection, tick: ScheduleTick) -> Any:
    return await conn.fetchrow(
        """
        INSERT INTO trendcite.cloud_schedule_tick
            (tick_id, schedule_id, workspace_id, radar_id, evaluation_cutoff,
             idempotency_key, status, attempt, max_attempts, lease_owner,
             lease_expires_at, run_id, skip_reason, error_code, error_detail,
             created_at, updated_at, started_at, finished_at)
        VALUES
            ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
        ON CONFLICT (workspace_id, idempotency_key) DO NOTHING
        RETURNING tick_id
        """,
        tick.tick_id,
        tick.schedule_id,
        tick.workspace_id,
        tick.radar_id,
        tick.evaluation_cutoff.isoformat(),
        tick.idempotency_key,
        tick.status,
        tick.attempt,
        tick.max_attempts,
        tick.lease_owner,
        None if tick.lease_expires_at is None else tick.lease_expires_at.isoformat(),
        tick.run_id,
        tick.skip_reason,
        tick.error_code,
        tick.error_detail,
        tick.created_at.isoformat(),
        tick.updated_at.isoformat(),
        None if tick.started_at is None else tick.started_at.isoformat(),
        None if tick.finished_at is None else tick.finished_at.isoformat(),
    )


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _schedule(row: Any) -> RadarSchedule:
    return RadarSchedule(
        schedule_id=str(row["schedule_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        enabled=bool(row["enabled"]),
        cadence=str(row["cadence"]),
        utc_offset_minutes=int(row["utc_offset_minutes"]),
        anchor_at=_parse_dt(row["anchor_at"]),
        max_catch_up=int(row["max_catch_up"]),
        lease_seconds=int(row["lease_seconds"]),
        max_attempts=int(row["max_attempts"]),
        cadence_version=str(row["cadence_version"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        last_planned_at=(
            None if row["last_planned_at"] is None else _parse_dt(row["last_planned_at"])
        ),
    )


def _tick(row: Any) -> ScheduleTick:
    return ScheduleTick(
        tick_id=str(row["tick_id"]),
        schedule_id=str(row["schedule_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        evaluation_cutoff=_parse_dt(row["evaluation_cutoff"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        lease_owner=str(row["lease_owner"]),
        lease_expires_at=(
            None if row["lease_expires_at"] is None else _parse_dt(row["lease_expires_at"])
        ),
        run_id=str(row["run_id"]),
        skip_reason=str(row["skip_reason"]),
        error_code=str(row["error_code"]),
        error_detail=str(row["error_detail"]),
        created_at=_parse_dt(row["created_at"]),
        updated_at=_parse_dt(row["updated_at"]),
        started_at=None if row["started_at"] is None else _parse_dt(row["started_at"]),
        finished_at=None if row["finished_at"] is None else _parse_dt(row["finished_at"]),
    )


def _run(row: Any) -> RadarRun:
    return RadarRun(
        run_id=str(row["run_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        radar_version_id=str(row["radar_version_id"]),
        evaluation_cutoff=_parse_dt(row["evaluation_cutoff"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        coverage_state=str(row["coverage_state"]),
        attempt=int(row["attempt"]),
        signal_count=int(row["signal_count"]),
        match_count=int(row["match_count"]),
        error_code=str(row["error_code"]),
        error_detail=str(row["error_detail"]),
        started_at=_parse_dt(row["started_at"]),
        finished_at=None if row["finished_at"] is None else _parse_dt(row["finished_at"]),
    )


def postgres_migration_batches(sql_files: list[str]) -> list[str]:
    """Wrap portable Cloud SQL migrations for administrative PostgreSQL execution.

    The Worker must never call this function.  The caller is an admin/deployment path
    that owns CREATE/ALTER authority; runtime roles should not.
    """

    prefix = "CREATE SCHEMA IF NOT EXISTS trendcite;\nSET search_path TO trendcite, pg_catalog;\n"
    return [prefix + sql for sql in sql_files]
