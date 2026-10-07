"""PostgreSQL operational store for TC-P007 automation readiness."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import ids
from ..domain.automation import (
    RECOVERY_EXPIRED_FINAL_TERMINAL,
    RECOVERY_EXPIRED_LEASE_REQUEUE,
    RECOVERY_FAILED_REQUEUE,
    RECOVERY_PENDING_REQUEUE,
    AutomationSummary,
    RecoveryCandidate,
)
from ..errors import NotFoundError
from .postgres import Connection, Connector

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresAutomationStore:
    def __init__(
        self,
        connector: Connector,
        *,
        runtime_role: str = "trendcite_runtime",
    ) -> None:
        if not _IDENTIFIER.fullmatch(runtime_role):
            raise ValueError("runtime role must be a PostgreSQL identifier")
        self._connector = connector
        self._runtime_role = runtime_role

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[Connection]:
        conn = await self._connector()
        try:
            async with conn.transaction():
                await conn.execute(f"SET LOCAL ROLE {self._runtime_role}")
                yield conn
        finally:
            await conn.close()

    async def record_heartbeat(
        self,
        component_key: str,
        *,
        observed_at: datetime,
        detail: dict[str, Any],
    ) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                """
                INSERT INTO trendcite.cloud_automation_heartbeat
                    (component_key, observed_at, detail_json)
                VALUES ($1,$2,$3)
                ON CONFLICT (component_key) DO UPDATE SET
                    observed_at=EXCLUDED.observed_at,
                    detail_json=EXCLUDED.detail_json
                """,
                component_key,
                observed_at.isoformat(),
                json.dumps(detail, sort_keys=True, separators=(",", ":")),
            )

    async def list_recovery_candidates(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int = 100,
    ) -> tuple[RecoveryCandidate, ...]:
        async with self._transaction() as conn:
            rows = await conn.fetch(
                """
                SELECT tick_id, schedule_id, workspace_id, status, attempt,
                       max_attempts, lease_expires_at, updated_at
                FROM trendcite.cloud_schedule_tick
                WHERE (
                       (status='pending' AND updated_at <= $1)
                    OR (status='failed' AND attempt < max_attempts AND updated_at <= $1)
                    OR (status='running' AND lease_expires_at IS NOT NULL
                                     AND lease_expires_at <= $2)
                )
                ORDER BY updated_at, tick_id
                LIMIT $3
                """,
                stale_before.isoformat(),
                now.isoformat(),
                int(limit),
            )

        candidates: list[RecoveryCandidate] = []
        for row in rows:
            status = str(row["status"])
            attempt = int(row["attempt"])
            max_attempts = int(row["max_attempts"])
            if status == "pending":
                action = RECOVERY_PENDING_REQUEUE
                reason = "pending tick exceeded stale threshold"
            elif status == "failed":
                action = RECOVERY_FAILED_REQUEUE
                reason = "retryable failed tick exceeded stale threshold"
            elif attempt >= max_attempts:
                action = RECOVERY_EXPIRED_FINAL_TERMINAL
                reason = "worker lease expired on final allowed attempt"
            else:
                action = RECOVERY_EXPIRED_LEASE_REQUEUE
                reason = "worker lease expired before attempt budget exhausted"
            candidates.append(
                RecoveryCandidate(
                    workspace_id=str(row["workspace_id"]),
                    tick_id=str(row["tick_id"]),
                    schedule_id=str(row["schedule_id"]),
                    status=status,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    action=action,
                    reason=reason,
                )
            )
        return tuple(candidates)

    async def recovery_action_exists(self, candidate: RecoveryCandidate) -> bool:
        async with self._transaction() as conn:
            value = await conn.fetchval(
                """
                SELECT 1
                FROM trendcite.cloud_recovery_action
                WHERE workspace_id=$1 AND tick_id=$2 AND attempt=$3 AND action=$4
                LIMIT 1
                """,
                candidate.workspace_id,
                candidate.tick_id,
                candidate.attempt,
                candidate.action,
            )
            return value is not None

    async def record_recovery_action(
        self,
        candidate: RecoveryCandidate,
        *,
        created_at: datetime,
    ) -> bool:
        action_id = ids.cloud_id(
            "recovery-action",
            candidate.workspace_id,
            candidate.tick_id,
            str(candidate.attempt),
            candidate.action,
        )
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO trendcite.cloud_recovery_action
                    (action_id, workspace_id, tick_id, attempt, action, reason, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (workspace_id, tick_id, attempt, action) DO NOTHING
                RETURNING action_id
                """,
                action_id,
                candidate.workspace_id,
                candidate.tick_id,
                candidate.attempt,
                candidate.action,
                candidate.reason,
                created_at.isoformat(),
            )
            return row is not None

    async def terminalize_expired_final_attempt(
        self,
        candidate: RecoveryCandidate,
        *,
        now: datetime,
    ) -> bool:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                UPDATE trendcite.cloud_schedule_tick
                SET status='failed',
                    lease_owner='',
                    lease_expires_at=NULL,
                    error_code='AttemptsExhausted',
                    error_detail='worker lease expired on final allowed attempt',
                    updated_at=$1,
                    finished_at=$1
                WHERE workspace_id=$2
                  AND tick_id=$3
                  AND status='running'
                  AND attempt >= max_attempts
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= $1
                RETURNING tick_id
                """,
                now.isoformat(),
                candidate.workspace_id,
                candidate.tick_id,
            )
            return row is not None

    async def record_queue_failure(
        self,
        *,
        workspace_id: str,
        logical_id: str,
        kind: str,
        queue_message_id: str,
        attempt: int,
        max_attempts: int,
        error_type: str,
        observed_at: datetime,
    ) -> bool:
        if not queue_message_id:
            return False
        failure_id = ids.cloud_id("queue-failure", queue_message_id, str(attempt))
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO trendcite.cloud_queue_failure_event
                    (failure_id, workspace_id, logical_id, kind, queue_message_id,
                     attempt, max_attempts, error_type, observed_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (queue_message_id, attempt) DO NOTHING
                RETURNING failure_id
                """,
                failure_id,
                workspace_id,
                logical_id,
                kind,
                queue_message_id,
                int(attempt),
                int(max_attempts),
                error_type[:120],
                observed_at.isoformat(),
            )
            return row is not None

    async def summary_for_principal(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        now: datetime,
        stale_seconds: int,
        scheduler_stale_seconds: int,
    ) -> AutomationSummary:
        stale_before = now - timedelta(seconds=stale_seconds)
        day_before = now - timedelta(hours=24)
        async with self._transaction() as conn:
            membership = await conn.fetchval(
                """
                SELECT role
                FROM trendcite.cloud_membership
                WHERE principal_id=$1 AND workspace_id=$2
                """,
                principal_id,
                workspace_id,
            )
            if membership is None:
                raise NotFoundError("workspace not found")

            heartbeat_value = await conn.fetchval(
                """
                SELECT observed_at
                FROM trendcite.cloud_automation_heartbeat
                WHERE component_key='scheduler'
                """
            )
            heartbeat = None if heartbeat_value is None else _parse_dt(heartbeat_value)

            schedule_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS enabled_count
                FROM trendcite.cloud_radar_schedule
                WHERE workspace_id=$1 AND enabled=1
                """,
                workspace_id,
            )
            schedule_rows = await conn.fetch(
                """
                SELECT cadence, anchor_at, last_planned_at
                FROM trendcite.cloud_radar_schedule
                WHERE workspace_id=$1 AND enabled=1
                """,
                workspace_id,
            )
            overdue = _overdue_schedule_count(schedule_rows, now)

            ticks = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(
                        CASE WHEN status='pending' AND updated_at <= $2
                             THEN 1 ELSE 0 END
                    ),0) AS pending_stale,
                    COALESCE(SUM(
                        CASE WHEN status='running'
                                  AND lease_expires_at IS NOT NULL
                                  AND lease_expires_at <= $3
                             THEN 1 ELSE 0 END
                    ),0) AS expired_running,
                    COALESCE(SUM(
                        CASE WHEN status='failed' AND attempt < max_attempts
                             THEN 1 ELSE 0 END
                    ),0) AS retryable_failed,
                    COALESCE(SUM(
                        CASE WHEN status='failed' AND attempt >= max_attempts
                             THEN 1 ELSE 0 END
                    ),0) AS exhausted_failed
                FROM trendcite.cloud_schedule_tick
                WHERE workspace_id=$1
                """,
                workspace_id,
                stale_before.isoformat(),
                now.isoformat(),
            )
            recovery_actions = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM trendcite.cloud_recovery_action
                    WHERE workspace_id=$1 AND created_at >= $2
                    """,
                    workspace_id,
                    day_before.isoformat(),
                )
                or 0
            )
            queue_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS failures,
                    COALESCE(SUM(CASE WHEN attempt >= max_attempts THEN 1 ELSE 0 END),0) AS at_limit
                FROM trendcite.cloud_queue_failure_event
                WHERE workspace_id=$1 AND observed_at >= $2
                """,
                workspace_id,
                day_before.isoformat(),
            )

        heartbeat_stale = heartbeat is None or heartbeat <= now - timedelta(
            seconds=scheduler_stale_seconds
        )
        return AutomationSummary(
            workspace_id=workspace_id,
            scheduler_last_seen_at=heartbeat,
            scheduler_stale=heartbeat_stale,
            enabled_schedules=int(schedule_row["enabled_count"] or 0),
            overdue_schedules=overdue,
            pending_stale_ticks=int(ticks["pending_stale"] or 0),
            expired_running_ticks=int(ticks["expired_running"] or 0),
            retryable_failed_ticks=int(ticks["retryable_failed"] or 0),
            exhausted_failed_ticks=int(ticks["exhausted_failed"] or 0),
            recovery_actions_24h=recovery_actions,
            queue_failures_24h=int(queue_row["failures"] or 0),
            queue_failures_at_retry_limit_24h=int(queue_row["at_limit"] or 0),
        )


def _overdue_schedule_count(rows: list[Any], now: datetime) -> int:
    periods = {
        "hourly": timedelta(hours=1),
        "six_hourly": timedelta(hours=6),
        "twelve_hourly": timedelta(hours=12),
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
    }
    overdue = 0
    for row in rows:
        anchor = _parse_dt(row["anchor_at"])
        if anchor > now:
            continue
        last_raw = row["last_planned_at"]
        if last_raw is None:
            overdue += 1
            continue
        last_planned = _parse_dt(last_raw)
        period = periods.get(str(row["cadence"]))
        if period is not None and last_planned + period <= now:
            overdue += 1
    return overdue


def _parse_dt(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
