"""PostgreSQL adapter for the async execution pipeline."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from ..async_execution import ExecutionPersistenceBundle
from ..domain.alerts import AlertBaseline, AlertPolicy
from ..domain.matches import Match
from ..domain.radar import RadarRun, RadarVersion
from ..domain.relevance import WatchlistSignalMatch
from ..domain.watchlist import WatchlistVersion
from .postgres import Connection, Connector

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresExecutionStore:
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

    async def get_radar_version(
        self,
        workspace_id: str,
        version_id: str,
    ) -> RadarVersion | None:
        conn = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_radar_version
                WHERE workspace_id=$1 AND version_id=$2
                """,
                workspace_id,
                version_id,
            )
            return None if row is None else _radar_version(row)
        finally:
            await conn.close()

    async def get_watchlist_version(
        self,
        workspace_id: str,
        version_id: str,
    ) -> WatchlistVersion | None:
        conn = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_watchlist_version
                WHERE workspace_id=$1 AND version_id=$2
                """,
                workspace_id,
                version_id,
            )
            return None if row is None else _watchlist_version(row)
        finally:
            await conn.close()

    async def get_watchlist_signal_match(
        self,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
    ) -> WatchlistSignalMatch | None:
        conn = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_watchlist_signal_match
                WHERE workspace_id=$1 AND watchlist_id=$2 AND signal_id=$3
                """,
                workspace_id,
                watchlist_id,
                signal_id,
            )
            return None if row is None else _watchlist_match(row)
        finally:
            await conn.close()

    async def get_match(
        self,
        workspace_id: str,
        radar_id: str,
        signal_id: str,
    ) -> Match | None:
        conn = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_match
                WHERE workspace_id=$1 AND radar_id=$2 AND signal_id=$3
                """,
                workspace_id,
                radar_id,
                signal_id,
            )
            return None if row is None else _match(row)
        finally:
            await conn.close()

    async def get_alert_policy(
        self,
        workspace_id: str,
        radar_id: str,
    ) -> AlertPolicy | None:
        conn = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_alert_policy
                WHERE workspace_id=$1 AND radar_id=$2
                """,
                workspace_id,
                radar_id,
            )
            return None if row is None else _alert_policy(row)
        finally:
            await conn.close()

    async def get_alert_baseline(
        self,
        workspace_id: str,
        watchlist_id: str,
        signal_id: str,
    ) -> AlertBaseline | None:
        conn = await self._connector()
        try:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_alert_baseline
                WHERE workspace_id=$1 AND watchlist_id=$2 AND signal_id=$3
                """,
                workspace_id,
                watchlist_id,
                signal_id,
            )
            return None if row is None else _alert_baseline(row)
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
            return _radar_run(row)

    async def get_run(self, workspace_id: str, run_id: str) -> RadarRun | None:
        conn = await self._connector()
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
            return None if row is None else _radar_run(row)
        finally:
            await conn.close()

    async def update_run(self, run: RadarRun) -> None:
        async with self._transaction() as conn:
            status = await conn.execute(
                """
                UPDATE trendcite.cloud_radar_run
                SET status=$1, coverage_state=$2, attempt=$3,
                    signal_count=$4, match_count=$5, error_code=$6,
                    error_detail=$7, started_at=$8, finished_at=$9
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

    async def persist_execution(self, bundle: ExecutionPersistenceBundle) -> RadarRun:
        async with self._transaction() as conn:
            for signal in bundle.signals:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_signal
                        (signal_id, signal_key, label, related_terms, first_seen_at,
                         last_seen_at, signal_id_version)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (signal_id) DO UPDATE SET
                        label=EXCLUDED.label,
                        related_terms=EXCLUDED.related_terms,
                        first_seen_at=LEAST(
                            trendcite.cloud_signal.first_seen_at,
                            EXCLUDED.first_seen_at
                        ),
                        last_seen_at=GREATEST(
                            trendcite.cloud_signal.last_seen_at,
                            EXCLUDED.last_seen_at
                        )
                    """,
                    signal.signal_id,
                    signal.signal_key,
                    signal.label,
                    _json(signal.related_terms),
                    signal.first_seen_at.isoformat(),
                    signal.last_seen_at.isoformat(),
                    signal.signal_id_version,
                )

            for snapshot in bundle.signal_evaluations:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_signal_evaluation
                        (snapshot_id, signal_id, captured_at, evaluation_version,
                         evidence_set_version, score, confidence, state,
                         observation_count, story_count, source_count, component_values)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (snapshot_id) DO NOTHING
                    """,
                    snapshot.snapshot_id,
                    snapshot.signal_id,
                    snapshot.captured_at.isoformat(),
                    snapshot.evaluation_version,
                    snapshot.evidence_set_version,
                    snapshot.score,
                    snapshot.confidence,
                    snapshot.state,
                    snapshot.observation_count,
                    snapshot.story_count,
                    snapshot.source_count,
                    _json(snapshot.component_values),
                )

            for relevance_evaluation in bundle.relevance_evaluations:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_relevance_evaluation
                        (evaluation_id, workspace_id, watchlist_id, watchlist_version_id,
                         signal_id, signal_snapshot_id, radar_id, radar_run_id, decision,
                         relevance_score, relevance_band, relevance_confidence,
                         reasons_json, components_json, matcher_version, evaluated_at)
                    VALUES
                        ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                    ON CONFLICT (evaluation_id) DO NOTHING
                    """,
                    relevance_evaluation.evaluation_id,
                    relevance_evaluation.workspace_id,
                    relevance_evaluation.watchlist_id,
                    relevance_evaluation.watchlist_version_id,
                    relevance_evaluation.signal_id,
                    relevance_evaluation.snapshot_id,
                    relevance_evaluation.radar_id,
                    relevance_evaluation.radar_run_id,
                    relevance_evaluation.decision,
                    relevance_evaluation.score,
                    relevance_evaluation.band,
                    relevance_evaluation.confidence,
                    _json([reason.to_dict() for reason in relevance_evaluation.reasons]),
                    _json([component.to_dict() for component in relevance_evaluation.components]),
                    relevance_evaluation.matcher_version,
                    relevance_evaluation.evaluated_at.isoformat(),
                )
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_relevance_evaluation_run
                        (evaluation_id, radar_run_id)
                    VALUES ($1,$2)
                    ON CONFLICT (evaluation_id, radar_run_id) DO NOTHING
                    """,
                    relevance_evaluation.evaluation_id,
                    bundle.run.run_id,
                )

            for watchlist_current in bundle.watchlist_matches:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_watchlist_signal_match
                        (match_id, workspace_id, watchlist_id, signal_id, status,
                         current_relevance_score, current_band, current_confidence,
                         current_evaluation_id, first_matched_at, last_matched_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (workspace_id, watchlist_id, signal_id) DO UPDATE SET
                        status=EXCLUDED.status,
                        current_relevance_score=EXCLUDED.current_relevance_score,
                        current_band=EXCLUDED.current_band,
                        current_confidence=EXCLUDED.current_confidence,
                        current_evaluation_id=EXCLUDED.current_evaluation_id,
                        last_matched_at=EXCLUDED.last_matched_at
                    """,
                    watchlist_current.match_id,
                    watchlist_current.workspace_id,
                    watchlist_current.watchlist_id,
                    watchlist_current.signal_id,
                    watchlist_current.status,
                    watchlist_current.current_relevance_score,
                    watchlist_current.current_band,
                    watchlist_current.current_confidence,
                    watchlist_current.current_evaluation_id,
                    watchlist_current.first_matched_at.isoformat(),
                    watchlist_current.last_matched_at.isoformat(),
                )

            for match_evaluation in bundle.match_evaluations:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_match_evaluation
                        (evaluation_id, workspace_id, radar_id, run_id,
                         watchlist_version_id, signal_id, decision, strength,
                         matched_terms, excluded_terms, matched_fields, explanation,
                         matcher_version, evaluated_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                    ON CONFLICT (evaluation_id) DO NOTHING
                    """,
                    match_evaluation.evaluation_id,
                    match_evaluation.workspace_id,
                    match_evaluation.radar_id,
                    match_evaluation.run_id,
                    match_evaluation.watchlist_version_id,
                    match_evaluation.signal_id,
                    match_evaluation.decision,
                    match_evaluation.strength,
                    _json(match_evaluation.matched_terms),
                    _json(match_evaluation.excluded_terms),
                    _json(match_evaluation.matched_fields),
                    match_evaluation.explanation,
                    match_evaluation.matcher_version,
                    match_evaluation.evaluated_at.isoformat(),
                )

            for radar_match in bundle.matches:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_match
                        (match_id, workspace_id, radar_id, signal_id, status, strength,
                         watchlist_version_id, matcher_version, first_matched_at,
                         last_matched_at, last_run_id)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (workspace_id, radar_id, signal_id) DO UPDATE SET
                        status=EXCLUDED.status,
                        strength=EXCLUDED.strength,
                        watchlist_version_id=EXCLUDED.watchlist_version_id,
                        matcher_version=EXCLUDED.matcher_version,
                        last_matched_at=EXCLUDED.last_matched_at,
                        last_run_id=EXCLUDED.last_run_id
                    """,
                    radar_match.match_id,
                    radar_match.workspace_id,
                    radar_match.radar_id,
                    radar_match.signal_id,
                    radar_match.status,
                    radar_match.strength,
                    radar_match.watchlist_version_id,
                    radar_match.matcher_version,
                    radar_match.first_matched_at.isoformat(),
                    radar_match.last_matched_at.isoformat(),
                    radar_match.last_run_id,
                )

            for edge in bundle.run_signals:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_run_signal
                        (run_signal_id, run_id, workspace_id, signal_id, snapshot_id, relevance)
                    VALUES ($1,$2,$3,$4,$5,$6)
                    ON CONFLICT (run_id, signal_id) DO UPDATE SET
                        snapshot_id=EXCLUDED.snapshot_id,
                        relevance=EXCLUDED.relevance
                    """,
                    edge.run_signal_id,
                    edge.run_id,
                    edge.workspace_id,
                    edge.signal_id,
                    edge.snapshot_id,
                    edge.relevance,
                )

            for coverage in bundle.coverage:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_run_coverage
                        (coverage_id, run_id, workspace_id, source, state,
                         item_count, detail, observed_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (run_id, source) DO UPDATE SET
                        state=EXCLUDED.state,
                        item_count=EXCLUDED.item_count,
                        detail=EXCLUDED.detail,
                        observed_at=EXCLUDED.observed_at
                    """,
                    coverage.coverage_id,
                    coverage.run_id,
                    coverage.workspace_id,
                    coverage.source,
                    coverage.state,
                    coverage.item_count,
                    coverage.detail,
                    coverage.observed_at.isoformat(),
                )

            for candidate in bundle.alert_candidates:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_alert_candidate
                        (candidate_id, workspace_id, radar_id, watchlist_id, signal_id,
                         signal_snapshot_id, run_id, subject_key, status, reason, label,
                         relevance_score, signal_score, lifecycle_state, velocity,
                         source_count, counterevidence, materiality, materiality_version,
                         evaluation_json, observed_at, created_at)
                    VALUES
                        ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                         $17,$18,$19,$20,$21,$22)
                    ON CONFLICT
                        (workspace_id, watchlist_id, signal_id, signal_snapshot_id,
                         materiality_version)
                    DO NOTHING
                    """,
                    candidate.candidate_id,
                    candidate.workspace_id,
                    candidate.radar_id,
                    candidate.watchlist_id,
                    candidate.signal_id,
                    candidate.snapshot_id,
                    candidate.run_id,
                    candidate.subject_key,
                    candidate.status,
                    candidate.reason,
                    candidate.label,
                    candidate.relevance_score,
                    candidate.signal_score,
                    candidate.lifecycle_state,
                    candidate.velocity,
                    candidate.source_count,
                    _json(candidate.counterevidence),
                    candidate.materiality,
                    candidate.materiality_version,
                    _json(candidate.evaluation.to_dict()),
                    candidate.observed_at.isoformat(),
                    candidate.created_at.isoformat(),
                )

            for event in bundle.usage_events:
                await conn.execute(
                    """
                    INSERT INTO trendcite.cloud_usage_event
                        (event_id, workspace_id, kind, quantity, occurred_at, run_id, dedupe_key)
                    VALUES ($1,$2,$3,$4,$5,$6,$7)
                    ON CONFLICT (workspace_id, dedupe_key) DO NOTHING
                    """,
                    event.event_id,
                    event.workspace_id,
                    event.kind,
                    event.quantity,
                    event.occurred_at.isoformat(),
                    event.run_id,
                    event.dedupe_key,
                )

            status = await conn.execute(
                """
                UPDATE trendcite.cloud_radar_run
                SET status=$1, coverage_state=$2, attempt=$3,
                    signal_count=$4, match_count=$5, error_code='',
                    error_detail='', finished_at=$6
                WHERE workspace_id=$7 AND run_id=$8
                """,
                bundle.run.status,
                bundle.run.coverage_state,
                bundle.run.attempt,
                bundle.run.signal_count,
                bundle.run.match_count,
                None if bundle.run.finished_at is None else bundle.run.finished_at.isoformat(),
                bundle.run.workspace_id,
                bundle.run.run_id,
            )
            if status.endswith(" 0"):
                raise RuntimeError("succeeded radar run update matched no row")
            return bundle.run


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _loads(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    return json.loads(str(value))


def _radar_version(row: Any) -> RadarVersion:
    return RadarVersion(
        version_id=str(row["version_id"]),
        radar_id=str(row["radar_id"]),
        workspace_id=str(row["workspace_id"]),
        version_number=int(row["version_number"]),
        watchlist_version_ids=tuple(str(x) for x in _loads(row["watchlist_version_ids"])),
        sources=tuple(str(x) for x in _loads(row["sources"])),
        niche=tuple(str(x) for x in _loads(row["niche"])),
        top=int(row["top"]),
        created_at=_parse_dt(row["created_at"]),
    )


def _watchlist_version(row: Any) -> WatchlistVersion:
    return WatchlistVersion(
        version_id=str(row["version_id"]),
        watchlist_id=str(row["watchlist_id"]),
        workspace_id=str(row["workspace_id"]),
        version_number=int(row["version_number"]),
        include_terms=tuple(str(x) for x in _loads(row["include_terms"])),
        exclude_terms=tuple(str(x) for x in _loads(row["exclude_terms"])),
        match_mode=str(row["match_mode"]),
        matcher_version=str(row["matcher_version"]),
        created_at=_parse_dt(row["created_at"]),
        entities=tuple(str(x) for x in _loads(row["entities"])),
        domains=tuple(str(x) for x in _loads(row["domains"])),
    )


def _watchlist_match(row: Any) -> WatchlistSignalMatch:
    return WatchlistSignalMatch(
        match_id=str(row["match_id"]),
        workspace_id=str(row["workspace_id"]),
        watchlist_id=str(row["watchlist_id"]),
        signal_id=str(row["signal_id"]),
        status=str(row["status"]),
        current_relevance_score=float(row["current_relevance_score"]),
        current_band=str(row["current_band"]),
        current_confidence=str(row["current_confidence"]),
        current_evaluation_id=str(row["current_evaluation_id"]),
        first_matched_at=_parse_dt(row["first_matched_at"]),
        last_matched_at=_parse_dt(row["last_matched_at"]),
    )


def _match(row: Any) -> Match:
    return Match(
        match_id=str(row["match_id"]),
        workspace_id=str(row["workspace_id"]),
        radar_id=str(row["radar_id"]),
        signal_id=str(row["signal_id"]),
        status=str(row["status"]),
        strength=float(row["strength"]),
        watchlist_version_id=str(row["watchlist_version_id"]),
        matcher_version=str(row["matcher_version"]),
        first_matched_at=_parse_dt(row["first_matched_at"]),
        last_matched_at=_parse_dt(row["last_matched_at"]),
        last_run_id=str(row["last_run_id"]),
    )


def _alert_policy(row: Any) -> AlertPolicy:
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
        updated_at=_parse_dt(row["updated_at"]),
    )


def _alert_baseline(row: Any) -> AlertBaseline:
    return AlertBaseline(
        baseline_id=str(row["baseline_id"]),
        workspace_id=str(row["workspace_id"]),
        watchlist_id=str(row["watchlist_id"]),
        signal_id=str(row["signal_id"]),
        alert_id=str(row["alert_id"]),
        snapshot_id=str(row["signal_snapshot_id"]),
        signal_score=float(row["signal_score"]),
        relevance_score=float(row["relevance_score"]),
        lifecycle_state=str(row["lifecycle_state"]),
        velocity=None if row["velocity"] is None else float(row["velocity"]),
        source_count=int(row["source_count"]),
        counterevidence=tuple(str(x) for x in _loads(row["counterevidence"])),
        delivered_at=_parse_dt(row["delivered_at"]),
        materiality_version=str(row["materiality_version"]),
    )


def _radar_run(row: Any) -> RadarRun:
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
