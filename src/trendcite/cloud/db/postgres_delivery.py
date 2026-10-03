"""PostgreSQL persistence for async alert, digest and delivery operations."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from ..domain.alerts import (
    Alert,
    AlertBaseline,
    AlertCandidate,
    AlertPolicy,
    DeliveryAttempt,
    MaterialityEvaluation,
)
from ..domain.digests import Digest, DigestItem
from .postgres import Connection, Connector

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresDeliveryStore:
    def __init__(self, connector: Connector, *, runtime_role: str = "trendcite_runtime") -> None:
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

    async def get_policy(self, workspace_id: str, radar_id: str) -> AlertPolicy | None:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_alert_policy
                WHERE workspace_id=$1 AND radar_id=$2
                """,
                workspace_id,
                radar_id,
            )
            return None if row is None else _policy(row)

    async def get_candidate(self, workspace_id: str, candidate_id: str) -> AlertCandidate | None:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_alert_candidate
                WHERE workspace_id=$1 AND candidate_id=$2
                """,
                workspace_id,
                candidate_id,
            )
            return None if row is None else _candidate(row)

    async def candidates_for_run(
        self,
        workspace_id: str,
        run_id: str,
    ) -> tuple[AlertCandidate, ...]:
        async with self._transaction() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM trendcite.cloud_alert_candidate
                WHERE workspace_id=$1 AND run_id=$2
                ORDER BY created_at, candidate_id
                """,
                workspace_id,
                run_id,
            )
            return tuple(_candidate(row) for row in rows)

    async def candidates_in_window(
        self,
        workspace_id: str,
        radar_id: str,
        start: str,
        end: str,
    ) -> tuple[AlertCandidate, ...]:
        async with self._transaction() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM trendcite.cloud_alert_candidate
                WHERE workspace_id=$1 AND radar_id=$2
                  AND observed_at >= $3 AND observed_at < $4
                ORDER BY observed_at, candidate_id
                """,
                workspace_id,
                radar_id,
                start,
                end,
            )
            return tuple(_candidate(row) for row in rows)

    async def get_alert(self, workspace_id: str, alert_id: str) -> Alert | None:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_alert
                WHERE workspace_id=$1 AND alert_id=$2
                """,
                workspace_id,
                alert_id,
            )
            return None if row is None else _alert(row)

    async def add_alert(self, alert: Alert) -> Alert:
        async with self._transaction() as conn:
            await conn.execute(
                """
                INSERT INTO trendcite.cloud_alert
                    (alert_id, workspace_id, radar_id, watchlist_id, signal_id,
                     signal_snapshot_id, candidate_id, subject_key, materiality,
                     relevance_score, signal_score, channel, delivery_state,
                     attempt_count, subject, body, renderer_version, created_at,
                     delivered_at)
                VALUES
                    ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                ON CONFLICT (candidate_id) DO NOTHING
                """,
                alert.alert_id,
                alert.workspace_id,
                alert.radar_id,
                alert.watchlist_id,
                alert.signal_id,
                alert.snapshot_id,
                alert.candidate_id,
                alert.subject_key,
                alert.materiality,
                alert.relevance_score,
                alert.signal_score,
                alert.channel,
                alert.delivery_state,
                alert.attempt_count,
                alert.subject,
                alert.body,
                alert.renderer_version,
                alert.created_at.isoformat(),
                None if alert.delivered_at is None else alert.delivered_at.isoformat(),
            )
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_alert
                WHERE workspace_id=$1 AND candidate_id=$2
                """,
                alert.workspace_id,
                alert.candidate_id,
            )
            if row is None:
                raise RuntimeError("alert insert was not observable")
            return _alert(row)

    async def update_alert(self, alert: Alert) -> None:
        async with self._transaction() as conn:
            status = await conn.execute(
                """
                UPDATE trendcite.cloud_alert
                SET delivery_state=$1, attempt_count=$2, delivered_at=$3
                WHERE workspace_id=$4 AND alert_id=$5
                """,
                alert.delivery_state,
                alert.attempt_count,
                None if alert.delivered_at is None else alert.delivered_at.isoformat(),
                alert.workspace_id,
                alert.alert_id,
            )
            if status.endswith(" 0"):
                raise RuntimeError("alert update matched no row")

    async def attempts_for(
        self,
        workspace_id: str,
        target_kind: str,
        target_id: str,
    ) -> tuple[DeliveryAttempt, ...]:
        async with self._transaction() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM trendcite.cloud_delivery_attempt
                WHERE workspace_id=$1 AND target_kind=$2 AND target_id=$3
                ORDER BY attempt_number
                """,
                workspace_id,
                target_kind,
                target_id,
            )
            return tuple(_attempt(row) for row in rows)

    async def record_attempt(self, attempt: DeliveryAttempt) -> bool:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO trendcite.cloud_delivery_attempt
                    (attempt_id, workspace_id, target_kind, target_id, attempt_number,
                     channel, status, provider, provider_reference, detail, attempted_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (workspace_id, target_kind, target_id, attempt_number)
                DO NOTHING
                RETURNING attempt_id
                """,
                attempt.attempt_id,
                attempt.workspace_id,
                attempt.target_kind,
                attempt.target_id,
                attempt.attempt_number,
                attempt.channel,
                attempt.status,
                attempt.provider,
                attempt.provider_reference,
                attempt.detail,
                attempt.attempted_at.isoformat(),
            )
            return row is not None

    async def upsert_baseline(self, baseline: AlertBaseline) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                """
                INSERT INTO trendcite.cloud_alert_baseline
                    (baseline_id, workspace_id, watchlist_id, signal_id, alert_id,
                     signal_snapshot_id, signal_score, relevance_score, lifecycle_state,
                     velocity, source_count, counterevidence, delivered_at,
                     materiality_version)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT (workspace_id, watchlist_id, signal_id) DO UPDATE SET
                    alert_id=EXCLUDED.alert_id,
                    signal_snapshot_id=EXCLUDED.signal_snapshot_id,
                    signal_score=EXCLUDED.signal_score,
                    relevance_score=EXCLUDED.relevance_score,
                    lifecycle_state=EXCLUDED.lifecycle_state,
                    velocity=EXCLUDED.velocity,
                    source_count=EXCLUDED.source_count,
                    counterevidence=EXCLUDED.counterevidence,
                    delivered_at=EXCLUDED.delivered_at,
                    materiality_version=EXCLUDED.materiality_version
                """,
                baseline.baseline_id,
                baseline.workspace_id,
                baseline.watchlist_id,
                baseline.signal_id,
                baseline.alert_id,
                baseline.snapshot_id,
                baseline.signal_score,
                baseline.relevance_score,
                baseline.lifecycle_state,
                baseline.velocity,
                baseline.source_count,
                _json(baseline.counterevidence),
                baseline.delivered_at.isoformat(),
                baseline.materiality_version,
            )

    async def get_digest(self, workspace_id: str, digest_id: str) -> Digest | None:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_digest
                WHERE workspace_id=$1 AND digest_id=$2
                """,
                workspace_id,
                digest_id,
            )
            return None if row is None else _digest(row)

    async def get_digest_by_date(
        self,
        workspace_id: str,
        radar_id: str,
        digest_date: str,
    ) -> Digest | None:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_digest
                WHERE workspace_id=$1 AND radar_id=$2 AND digest_date=$3
                """,
                workspace_id,
                radar_id,
                digest_date,
            )
            return None if row is None else _digest(row)

    async def upsert_digest(self, digest: Digest) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                """
                INSERT INTO trendcite.cloud_digest
                    (digest_id, workspace_id, radar_id, digest_date, window_start,
                     window_end, item_count, channel, delivery_state, attempt_count,
                     subject, body, renderer_version, created_at, delivered_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                ON CONFLICT (workspace_id, radar_id, digest_date) DO UPDATE SET
                    item_count=EXCLUDED.item_count,
                    channel=EXCLUDED.channel,
                    delivery_state=EXCLUDED.delivery_state,
                    attempt_count=EXCLUDED.attempt_count,
                    subject=EXCLUDED.subject,
                    body=EXCLUDED.body,
                    renderer_version=EXCLUDED.renderer_version,
                    delivered_at=EXCLUDED.delivered_at
                """,
                digest.digest_id,
                digest.workspace_id,
                digest.radar_id,
                digest.digest_date,
                digest.window_start.isoformat(),
                digest.window_end.isoformat(),
                digest.item_count,
                digest.channel,
                digest.delivery_state,
                digest.attempt_count,
                digest.subject,
                digest.body,
                digest.renderer_version,
                digest.created_at.isoformat(),
                None if digest.delivered_at is None else digest.delivered_at.isoformat(),
            )

    async def replace_digest_items(
        self,
        workspace_id: str,
        digest_id: str,
        items: tuple[DigestItem, ...],
    ) -> None:
        async with self._transaction() as conn:
            await conn.execute(
                """
                DELETE FROM trendcite.cloud_digest_item
                WHERE workspace_id=$1 AND digest_id=$2
                """,
                workspace_id,
                digest_id,
            )
            for item in items:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_digest_item
                        (item_id, digest_id, workspace_id, signal_id, candidate_id,
                         signal_snapshot_id, rank, label, materiality, relevance_score,
                         signal_score, observed_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    """,
                    item.item_id,
                    item.digest_id,
                    item.workspace_id,
                    item.signal_id,
                    item.candidate_id,
                    item.snapshot_id,
                    item.rank,
                    item.label,
                    item.materiality,
                    item.relevance_score,
                    item.signal_score,
                    item.observed_at.isoformat(),
                )


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    return json.loads(str(value))


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _policy(row: Any) -> AlertPolicy:
    return AlertPolicy(
        policy_id=str(row["policy_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        enabled=bool(row["enabled"]),
        immediate_alerts=bool(row["immediate_alerts"]),
        daily_digest=bool(row["daily_digest"]),
        min_relevance=float(row["min_relevance"]),
        min_materiality=str(row["min_materiality"]),
        cooldown_hours=float(row["cooldown_hours"]),
        digest_max_items=int(row["digest_max_items"]),
        max_delivery_attempts=int(row["max_delivery_attempts"]),
        channel=str(row["channel"]),
        policy_version=str(row["policy_version"]),
        updated_at=_dt(row["updated_at"]),
    )


def _candidate(row: Any) -> AlertCandidate:
    return AlertCandidate(
        candidate_id=str(row["candidate_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        watchlist_id=str(row["watchlist_id"]),
        signal_id=str(row["signal_id"]),
        snapshot_id=str(row["signal_snapshot_id"]),
        run_id=str(row["run_id"]),
        subject_key=str(row["subject_key"]),
        status=str(row["status"]),
        reason=str(row["reason"]),
        label=str(row["label"]),
        relevance_score=float(row["relevance_score"]),
        signal_score=float(row["signal_score"]),
        lifecycle_state=str(row["lifecycle_state"]),
        velocity=None if row["velocity"] is None else float(row["velocity"]),
        source_count=int(row["source_count"]),
        counterevidence=tuple(str(x) for x in _loads(row["counterevidence"])),
        materiality=str(row["materiality"]),
        materiality_version=str(row["materiality_version"]),
        evaluation=MaterialityEvaluation.from_dict(_loads(row["evaluation_json"])),
        observed_at=_dt(row["observed_at"]),
        created_at=_dt(row["created_at"]),
    )


def _alert(row: Any) -> Alert:
    return Alert(
        alert_id=str(row["alert_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        watchlist_id=str(row["watchlist_id"]),
        signal_id=str(row["signal_id"]),
        snapshot_id=str(row["signal_snapshot_id"]),
        candidate_id=str(row["candidate_id"]),
        subject_key=str(row["subject_key"]),
        materiality=str(row["materiality"]),
        relevance_score=float(row["relevance_score"]),
        signal_score=float(row["signal_score"]),
        channel=str(row["channel"]),
        delivery_state=str(row["delivery_state"]),
        attempt_count=int(row["attempt_count"]),
        subject=str(row["subject"]),
        body=str(row["body"]),
        renderer_version=str(row["renderer_version"]),
        created_at=_dt(row["created_at"]),
        delivered_at=None if row["delivered_at"] is None else _dt(row["delivered_at"]),
    )


def _attempt(row: Any) -> DeliveryAttempt:
    return DeliveryAttempt(
        attempt_id=str(row["attempt_id"]),
        workspace_id=str(row["workspace_id"]),
        target_kind=str(row["target_kind"]),
        target_id=str(row["target_id"]),
        attempt_number=int(row["attempt_number"]),
        channel=str(row["channel"]),
        status=str(row["status"]),
        provider=str(row["provider"]),
        provider_reference=str(row["provider_reference"]),
        detail=str(row["detail"]),
        attempted_at=_dt(row["attempted_at"]),
    )


def _digest(row: Any) -> Digest:
    return Digest(
        digest_id=str(row["digest_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        digest_date=str(row["digest_date"]),
        window_start=_dt(row["window_start"]),
        window_end=_dt(row["window_end"]),
        item_count=int(row["item_count"]),
        channel=str(row["channel"]),
        delivery_state=str(row["delivery_state"]),
        attempt_count=int(row["attempt_count"]),
        subject=str(row["subject"]),
        body=str(row["body"]),
        renderer_version=str(row["renderer_version"]),
        created_at=_dt(row["created_at"]),
        delivered_at=None if row["delivered_at"] is None else _dt(row["delivered_at"]),
    )
