"""Membership-scoped customer data access for the TrendCite customer API.

Every public method takes the authenticated ``principal_id`` and the requested
``workspace_id`` and resolves ``trendcite.cloud_membership`` *inside the same
transaction* as the data it reads or writes. There is no method that accepts a
workspace id without a principal, so a route cannot forget the check.

Disclosure rules, enforced here rather than in the router:

* a principal without membership gets :class:`NotFoundError` -- never a distinct
  "forbidden" -- so workspace existence does not leak across tenants;
* an object id that exists only in *another* workspace is likewise
  :class:`NotFoundError`, because every object query is filtered by workspace_id;
* a ``viewer`` that attempts a write gets :class:`PermissionDeniedError`, which is
  only reachable after membership is proven.

Watchlist and radar versions are append-only. An edit locks the parent row
(``FOR UPDATE``), derives ``max(version_number) + 1`` and inserts with
``ON CONFLICT DO NOTHING``; a writer that still loses the race receives
:class:`ConflictError` instead of overwriting or duplicating a version.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from ..domain.radar import Radar, RadarVersion
from ..domain.watchlist import MODE_ANY, Watchlist, WatchlistVersion
from ..errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from .postgres import Connection, Connector
from .postgres_access import PostgresAccessStore

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Roles that may mutate customer configuration. ``viewer`` is read-only.
WRITE_ROLES = frozenset({"owner", "admin", "member"})

#: Sources a customer radar may name. X stays interface-only and is not offered.
CUSTOMER_SOURCES = ("hackernews", "github", "rss", "reddit")

MAX_LIMIT = 100
DEFAULT_LIMIT = 50
MAX_RADAR_WATCHLISTS = 20


class PostgresCustomerStore(PostgresAccessStore):
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

    # ------------------------------------------------------------------ membership

    async def _require_member(
        self,
        conn: Connection,
        principal_id: str,
        workspace_id: str,
        *,
        write: bool = False,
    ) -> str:
        # FOR SHARE holds the membership row for the rest of a write transaction, so a
        # concurrent revocation cannot interleave between the check and the write.
        if write:
            role = await conn.fetchval(
                """
                SELECT role
                FROM trendcite.cloud_membership
                WHERE principal_id=$1 AND workspace_id=$2
                FOR SHARE
                """,
                principal_id,
                workspace_id,
            )
        else:
            role = await conn.fetchval(
                """
                SELECT role
                FROM trendcite.cloud_membership
                WHERE principal_id=$1 AND workspace_id=$2
                """,
                principal_id,
                workspace_id,
            )
        if role is None:
            raise NotFoundError("workspace not found")
        role = str(role)
        if write and role not in WRITE_ROLES:
            raise PermissionDeniedError("role does not permit changes")
        return role

    # ------------------------------------------------------------------ watchlists

    async def list_watchlists(self, principal_id: str, workspace_id: str) -> list[dict[str, Any]]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            rows = await conn.fetch(
                """
                SELECT w.watchlist_id, w.name, w.created_at,
                       v.version_id, v.version_number, v.include_terms, v.exclude_terms,
                       v.match_mode, v.entities, v.domains, v.matcher_version,
                       v.created_at AS version_created_at
                FROM trendcite.cloud_watchlist AS w
                LEFT JOIN trendcite.cloud_watchlist_version AS v
                  ON v.workspace_id=w.workspace_id
                 AND v.watchlist_id=w.watchlist_id
                 AND v.version_number=(
                     SELECT MAX(v2.version_number)
                     FROM trendcite.cloud_watchlist_version AS v2
                     WHERE v2.workspace_id=w.workspace_id
                       AND v2.watchlist_id=w.watchlist_id)
                WHERE w.workspace_id=$1
                ORDER BY w.name, w.watchlist_id
                """,
                workspace_id,
            )
            return [_watchlist_summary(row) for row in rows]

    async def get_watchlist(
        self, principal_id: str, workspace_id: str, watchlist_id: str
    ) -> dict[str, Any]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            row = await conn.fetchrow(
                """
                SELECT watchlist_id, name, created_at
                FROM trendcite.cloud_watchlist
                WHERE workspace_id=$1 AND watchlist_id=$2
                """,
                workspace_id,
                watchlist_id,
            )
            if row is None:
                raise NotFoundError("watchlist not found")
            versions = await conn.fetch(
                """
                SELECT *
                FROM trendcite.cloud_watchlist_version
                WHERE workspace_id=$1 AND watchlist_id=$2
                ORDER BY version_number DESC
                """,
                workspace_id,
                watchlist_id,
            )
            return {
                "watchlist_id": str(row["watchlist_id"]),
                "name": str(row["name"]),
                "created_at": _ts(row["created_at"]),
                "versions": [_watchlist_version(v) for v in versions],
            }

    async def create_watchlist(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        name: str,
        include_terms: Iterable[str],
        exclude_terms: Iterable[str] = (),
        match_mode: str = MODE_ANY,
        entities: Iterable[str] = (),
        domains: Iterable[str] = (),
        now: datetime,
    ) -> dict[str, Any]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id, write=True)
            watchlist = Watchlist.create(workspace_id=workspace_id, name=name, created_at=now)
            version = WatchlistVersion.create(
                watchlist_id=watchlist.watchlist_id,
                workspace_id=workspace_id,
                version_number=1,
                include_terms=include_terms,
                exclude_terms=exclude_terms,
                match_mode=match_mode,
                entities=entities,
                domains=domains,
                created_at=now,
            )
            inserted = await conn.fetchval(
                """
                INSERT INTO trendcite.cloud_watchlist
                    (watchlist_id, workspace_id, name, created_at)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT DO NOTHING
                RETURNING watchlist_id
                """,
                watchlist.watchlist_id,
                workspace_id,
                watchlist.name,
                watchlist.created_at.isoformat(),
            )
            if inserted is None:
                raise ConflictError("a watchlist with this name already exists")
            await _insert_watchlist_version(conn, version)
            return {
                "watchlist_id": watchlist.watchlist_id,
                "name": watchlist.name,
                "created_at": watchlist.created_at.isoformat(),
                "versions": [_version_dict(version)],
            }

    async def append_watchlist_version(
        self,
        principal_id: str,
        workspace_id: str,
        watchlist_id: str,
        *,
        include_terms: Iterable[str],
        exclude_terms: Iterable[str] = (),
        match_mode: str = MODE_ANY,
        entities: Iterable[str] = (),
        domains: Iterable[str] = (),
        expected_version_number: int | None = None,
        now: datetime,
    ) -> tuple[dict[str, Any], bool]:
        """Append the next immutable version. Returns ``(version, created)``.

        Re-submitting content identical to the latest version is idempotent: the latest
        version is returned with ``created=False`` rather than minting a duplicate.
        """
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id, write=True)
            parent = await conn.fetchval(
                """
                SELECT watchlist_id
                FROM trendcite.cloud_watchlist
                WHERE workspace_id=$1 AND watchlist_id=$2
                FOR UPDATE
                """,
                workspace_id,
                watchlist_id,
            )
            if parent is None:
                raise NotFoundError("watchlist not found")
            latest_row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_watchlist_version
                WHERE workspace_id=$1 AND watchlist_id=$2
                ORDER BY version_number DESC
                LIMIT 1
                """,
                workspace_id,
                watchlist_id,
            )
            latest_number = 0 if latest_row is None else int(latest_row["version_number"])
            if expected_version_number is not None and expected_version_number != latest_number:
                raise ConflictError("watchlist changed since it was loaded")
            candidate = WatchlistVersion.create(
                watchlist_id=watchlist_id,
                workspace_id=workspace_id,
                version_number=latest_number + 1,
                include_terms=include_terms,
                exclude_terms=exclude_terms,
                match_mode=match_mode,
                entities=entities,
                domains=domains,
                created_at=now,
            )
            if latest_row is not None:
                latest = _watchlist_version(latest_row)
                if _same_watchlist_content(latest, candidate):
                    return latest, False
            await _insert_watchlist_version(conn, candidate)
            return _version_dict(candidate), True

    # ---------------------------------------------------------------------- radars

    async def list_radars(self, principal_id: str, workspace_id: str) -> list[dict[str, Any]]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            rows = await conn.fetch(
                """
                SELECT r.radar_id, r.name, r.created_at,
                       v.version_id, v.version_number, v.watchlist_version_ids,
                       v.sources, v.niche, v.top, v.created_at AS version_created_at
                FROM trendcite.cloud_radar AS r
                LEFT JOIN trendcite.cloud_radar_version AS v
                  ON v.workspace_id=r.workspace_id
                 AND v.radar_id=r.radar_id
                 AND v.version_number=(
                     SELECT MAX(v2.version_number)
                     FROM trendcite.cloud_radar_version AS v2
                     WHERE v2.workspace_id=r.workspace_id AND v2.radar_id=r.radar_id)
                WHERE r.workspace_id=$1
                ORDER BY r.name, r.radar_id
                """,
                workspace_id,
            )
            return [_radar_summary(row) for row in rows]

    async def get_radar(
        self, principal_id: str, workspace_id: str, radar_id: str
    ) -> dict[str, Any]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            row = await conn.fetchrow(
                """
                SELECT radar_id, name, created_at
                FROM trendcite.cloud_radar
                WHERE workspace_id=$1 AND radar_id=$2
                """,
                workspace_id,
                radar_id,
            )
            if row is None:
                raise NotFoundError("radar not found")
            versions = await conn.fetch(
                """
                SELECT *
                FROM trendcite.cloud_radar_version
                WHERE workspace_id=$1 AND radar_id=$2
                ORDER BY version_number DESC
                """,
                workspace_id,
                radar_id,
            )
            return {
                "radar_id": str(row["radar_id"]),
                "name": str(row["name"]),
                "created_at": _ts(row["created_at"]),
                "versions": [_radar_version(v) for v in versions],
            }

    async def create_radar(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        name: str,
        watchlist_ids: Sequence[str],
        sources: Iterable[str],
        niche: Iterable[str] = (),
        top: int = 5,
        now: datetime,
    ) -> dict[str, Any]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id, write=True)
            radar = Radar.create(workspace_id=workspace_id, name=name, created_at=now)
            wanted_sources = _customer_sources(sources)
            pinned = await _pin_latest_versions(conn, workspace_id, watchlist_ids)
            version = RadarVersion.create(
                radar_id=radar.radar_id,
                workspace_id=workspace_id,
                version_number=1,
                watchlist_version_ids=pinned,
                sources=wanted_sources,
                niche=niche,
                top=top,
                created_at=now,
            )
            inserted = await conn.fetchval(
                """
                INSERT INTO trendcite.cloud_radar (radar_id, workspace_id, name, created_at)
                VALUES ($1,$2,$3,$4)
                ON CONFLICT DO NOTHING
                RETURNING radar_id
                """,
                radar.radar_id,
                workspace_id,
                radar.name,
                radar.created_at.isoformat(),
            )
            if inserted is None:
                raise ConflictError("a radar with this name already exists")
            await _insert_radar_version(conn, version)
            return {
                "radar_id": radar.radar_id,
                "name": radar.name,
                "created_at": radar.created_at.isoformat(),
                "versions": [_radar_version_dict(version)],
            }

    async def append_radar_version(
        self,
        principal_id: str,
        workspace_id: str,
        radar_id: str,
        *,
        watchlist_ids: Sequence[str],
        sources: Iterable[str],
        niche: Iterable[str] = (),
        top: int = 5,
        expected_version_number: int | None = None,
        now: datetime,
    ) -> tuple[dict[str, Any], bool]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id, write=True)
            parent = await conn.fetchval(
                """
                SELECT radar_id
                FROM trendcite.cloud_radar
                WHERE workspace_id=$1 AND radar_id=$2
                FOR UPDATE
                """,
                workspace_id,
                radar_id,
            )
            if parent is None:
                raise NotFoundError("radar not found")
            latest_row = await conn.fetchrow(
                """
                SELECT *
                FROM trendcite.cloud_radar_version
                WHERE workspace_id=$1 AND radar_id=$2
                ORDER BY version_number DESC
                LIMIT 1
                """,
                workspace_id,
                radar_id,
            )
            latest_number = 0 if latest_row is None else int(latest_row["version_number"])
            if expected_version_number is not None and expected_version_number != latest_number:
                raise ConflictError("radar changed since it was loaded")
            wanted_sources = _customer_sources(sources)
            pinned = await _pin_latest_versions(conn, workspace_id, watchlist_ids)
            candidate = RadarVersion.create(
                radar_id=radar_id,
                workspace_id=workspace_id,
                version_number=latest_number + 1,
                watchlist_version_ids=pinned,
                sources=wanted_sources,
                niche=niche,
                top=top,
                created_at=now,
            )
            if latest_row is not None:
                latest = _radar_version(latest_row)
                if _same_radar_content(latest, candidate):
                    return latest, False
            await _insert_radar_version(conn, candidate)
            return _radar_version_dict(candidate), True

    # ------------------------------------------------------------------------ runs

    async def list_runs(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        radar_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            query = """
                SELECT r.run_id, r.radar_id, rd.name AS radar_name, r.radar_version_id,
                       r.evaluation_cutoff, r.status, r.coverage_state, r.attempt,
                       r.signal_count, r.match_count, r.error_code, r.error_detail,
                       r.started_at, r.finished_at
                FROM trendcite.cloud_radar_run AS r
                JOIN trendcite.cloud_radar AS rd
                  ON rd.radar_id=r.radar_id AND rd.workspace_id=r.workspace_id
                WHERE r.workspace_id=$1
            """
            if radar_id is None:
                rows = await conn.fetch(
                    query + " ORDER BY r.started_at DESC, r.run_id LIMIT $2",
                    workspace_id,
                    _limit(limit),
                )
            else:
                rows = await conn.fetch(
                    query + " AND r.radar_id=$2 ORDER BY r.started_at DESC, r.run_id LIMIT $3",
                    workspace_id,
                    radar_id,
                    _limit(limit),
                )
            return [_run(row) for row in rows]

    async def get_run(self, principal_id: str, workspace_id: str, run_id: str) -> dict[str, Any]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            row = await conn.fetchrow(
                """
                SELECT r.run_id, r.radar_id, rd.name AS radar_name, r.radar_version_id,
                       r.evaluation_cutoff, r.status, r.coverage_state, r.attempt,
                       r.signal_count, r.match_count, r.error_code, r.error_detail,
                       r.started_at, r.finished_at
                FROM trendcite.cloud_radar_run AS r
                JOIN trendcite.cloud_radar AS rd
                  ON rd.radar_id=r.radar_id AND rd.workspace_id=r.workspace_id
                WHERE r.workspace_id=$1 AND r.run_id=$2
                """,
                workspace_id,
                run_id,
            )
            if row is None:
                raise NotFoundError("run not found")
            coverage = await conn.fetch(
                """
                SELECT source, state, item_count, detail, observed_at
                FROM trendcite.cloud_run_coverage
                WHERE workspace_id=$1 AND run_id=$2
                ORDER BY source
                """,
                workspace_id,
                run_id,
            )
            signals = await conn.fetch(
                """
                SELECT rs.signal_id, rs.snapshot_id, rs.relevance, s.label, s.related_terms,
                       e.score, e.confidence, e.state, e.observation_count, e.story_count,
                       e.source_count, e.captured_at
                FROM trendcite.cloud_run_signal AS rs
                JOIN trendcite.cloud_signal AS s ON s.signal_id=rs.signal_id
                JOIN trendcite.cloud_signal_evaluation AS e ON e.snapshot_id=rs.snapshot_id
                WHERE rs.workspace_id=$1 AND rs.run_id=$2
                ORDER BY rs.relevance DESC, e.score DESC, rs.signal_id
                LIMIT 200
                """,
                workspace_id,
                run_id,
            )
            result = _run(row)
            result["coverage"] = [
                {
                    "source": str(c["source"]),
                    "state": str(c["state"]),
                    "item_count": int(c["item_count"]),
                    "detail": str(c["detail"]),
                    "observed_at": _ts(c["observed_at"]),
                }
                for c in coverage
            ]
            result["signals"] = [_run_signal(s) for s in signals]
            return result

    # --------------------------------------------------------------------- signals

    async def list_signals(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        radar_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            query = """
                SELECT m.radar_id, rd.name AS radar_name, m.signal_id, s.label,
                       s.related_terms, m.status, m.strength, m.first_matched_at,
                       m.last_matched_at, m.last_run_id
                FROM trendcite.cloud_match AS m
                JOIN trendcite.cloud_signal AS s ON s.signal_id=m.signal_id
                JOIN trendcite.cloud_radar AS rd
                  ON rd.radar_id=m.radar_id AND rd.workspace_id=m.workspace_id
                WHERE m.workspace_id=$1
            """
            order = " ORDER BY m.last_matched_at DESC, m.strength DESC, m.signal_id"
            if radar_id is None:
                rows = await conn.fetch(query + order + " LIMIT $2", workspace_id, _limit(limit))
            else:
                rows = await conn.fetch(
                    query + " AND m.radar_id=$2" + order + " LIMIT $3",
                    workspace_id,
                    radar_id,
                    _limit(limit),
                )
            return [
                {
                    "radar_id": str(row["radar_id"]),
                    "radar_name": str(row["radar_name"]),
                    "signal_id": str(row["signal_id"]),
                    "label": str(row["label"]),
                    "related_terms": _str_list(row["related_terms"]),
                    "status": str(row["status"]),
                    "strength": float(row["strength"]),
                    "first_matched_at": _ts(row["first_matched_at"]),
                    "last_matched_at": _ts(row["last_matched_at"]),
                    "last_run_id": str(row["last_run_id"]),
                }
                for row in rows
            ]

    async def get_signal_history(
        self, principal_id: str, workspace_id: str, signal_id: str
    ) -> dict[str, Any]:
        """A signal as *this workspace* observed it.

        Signals are globally canonical, but history is assembled only from this
        workspace's own run edges and match evaluations. Global first/last-seen times
        and evaluations reached only through other tenants' runs are never returned,
        so the response cannot reveal what another workspace monitors or when.
        """
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            row = await conn.fetchrow(
                """
                SELECT s.signal_id, s.label, s.related_terms
                FROM trendcite.cloud_signal AS s
                WHERE s.signal_id=$2
                  AND EXISTS (
                      SELECT 1 FROM trendcite.cloud_run_signal AS rs
                      WHERE rs.workspace_id=$1 AND rs.signal_id=s.signal_id)
                """,
                workspace_id,
                signal_id,
            )
            if row is None:
                raise NotFoundError("signal not found")
            points = await conn.fetch(
                """
                SELECT rs.run_id, r.radar_id, r.evaluation_cutoff, rs.relevance,
                       e.snapshot_id, e.captured_at, e.score, e.confidence, e.state,
                       e.observation_count, e.story_count, e.source_count
                FROM trendcite.cloud_run_signal AS rs
                JOIN trendcite.cloud_radar_run AS r
                  ON r.run_id=rs.run_id AND r.workspace_id=rs.workspace_id
                JOIN trendcite.cloud_signal_evaluation AS e ON e.snapshot_id=rs.snapshot_id
                WHERE rs.workspace_id=$1 AND rs.signal_id=$2
                ORDER BY e.captured_at DESC, rs.run_id
                LIMIT 100
                """,
                workspace_id,
                signal_id,
            )
            evaluations = await conn.fetch(
                """
                SELECT radar_id, run_id, decision, strength, matched_terms,
                       excluded_terms, explanation, evaluated_at
                FROM trendcite.cloud_match_evaluation
                WHERE workspace_id=$1 AND signal_id=$2
                ORDER BY evaluated_at DESC, run_id
                LIMIT 100
                """,
                workspace_id,
                signal_id,
            )
            return {
                "signal_id": str(row["signal_id"]),
                "label": str(row["label"]),
                "related_terms": _str_list(row["related_terms"]),
                "history": [
                    {
                        "run_id": str(p["run_id"]),
                        "radar_id": str(p["radar_id"]),
                        "evaluation_cutoff": _ts(p["evaluation_cutoff"]),
                        "relevance": float(p["relevance"]),
                        "snapshot_id": str(p["snapshot_id"]),
                        "captured_at": _ts(p["captured_at"]),
                        "score": float(p["score"]),
                        "confidence": str(p["confidence"]),
                        "state": str(p["state"]),
                        "observation_count": int(p["observation_count"]),
                        "story_count": int(p["story_count"]),
                        "source_count": int(p["source_count"]),
                    }
                    for p in points
                ],
                "match_evaluations": [
                    {
                        "radar_id": str(m["radar_id"]),
                        "run_id": str(m["run_id"]),
                        "decision": str(m["decision"]),
                        "strength": float(m["strength"]),
                        "matched_terms": _str_list(m["matched_terms"]),
                        "excluded_terms": _str_list(m["excluded_terms"]),
                        "explanation": str(m["explanation"]),
                        "evaluated_at": _ts(m["evaluated_at"]),
                    }
                    for m in evaluations
                ],
            }

    # -------------------------------------------------------------- alerts/digests

    async def list_alerts(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        radar_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            query = """
                SELECT a.alert_id, a.radar_id, rd.name AS radar_name, a.watchlist_id,
                       a.signal_id, a.materiality, a.relevance_score, a.signal_score,
                       a.channel, a.delivery_state, a.attempt_count, a.subject, a.body,
                       a.created_at, a.delivered_at
                FROM trendcite.cloud_alert AS a
                JOIN trendcite.cloud_radar AS rd
                  ON rd.radar_id=a.radar_id AND rd.workspace_id=a.workspace_id
                WHERE a.workspace_id=$1
            """
            order = " ORDER BY a.created_at DESC, a.alert_id"
            if radar_id is None:
                rows = await conn.fetch(query + order + " LIMIT $2", workspace_id, _limit(limit))
            else:
                rows = await conn.fetch(
                    query + " AND a.radar_id=$2" + order + " LIMIT $3",
                    workspace_id,
                    radar_id,
                    _limit(limit),
                )
            return [
                {
                    "alert_id": str(row["alert_id"]),
                    "radar_id": str(row["radar_id"]),
                    "radar_name": str(row["radar_name"]),
                    "watchlist_id": str(row["watchlist_id"]),
                    "signal_id": str(row["signal_id"]),
                    "materiality": str(row["materiality"]),
                    "relevance_score": float(row["relevance_score"]),
                    "signal_score": float(row["signal_score"]),
                    "channel": str(row["channel"]),
                    "delivery_state": str(row["delivery_state"]),
                    "attempt_count": int(row["attempt_count"]),
                    "subject": str(row["subject"]),
                    "body": str(row["body"]),
                    "created_at": _ts(row["created_at"]),
                    "delivered_at": _ts_or_none(row["delivered_at"]),
                }
                for row in rows
            ]

    async def list_digests(
        self,
        principal_id: str,
        workspace_id: str,
        *,
        radar_id: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[dict[str, Any]]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            query = """
                SELECT d.digest_id, d.radar_id, rd.name AS radar_name, d.digest_date,
                       d.window_start, d.window_end, d.item_count, d.channel,
                       d.delivery_state, d.attempt_count, d.subject, d.created_at,
                       d.delivered_at
                FROM trendcite.cloud_digest AS d
                JOIN trendcite.cloud_radar AS rd
                  ON rd.radar_id=d.radar_id AND rd.workspace_id=d.workspace_id
                WHERE d.workspace_id=$1
            """
            order = " ORDER BY d.digest_date DESC, d.digest_id"
            if radar_id is None:
                rows = await conn.fetch(query + order + " LIMIT $2", workspace_id, _limit(limit))
            else:
                rows = await conn.fetch(
                    query + " AND d.radar_id=$2" + order + " LIMIT $3",
                    workspace_id,
                    radar_id,
                    _limit(limit),
                )
            return [_digest(row) for row in rows]

    async def get_digest(
        self, principal_id: str, workspace_id: str, digest_id: str
    ) -> dict[str, Any]:
        async with self._transaction() as conn:
            await self._require_member(conn, principal_id, workspace_id)
            row = await conn.fetchrow(
                """
                SELECT d.digest_id, d.radar_id, rd.name AS radar_name, d.digest_date,
                       d.window_start, d.window_end, d.item_count, d.channel,
                       d.delivery_state, d.attempt_count, d.subject, d.body, d.created_at,
                       d.delivered_at
                FROM trendcite.cloud_digest AS d
                JOIN trendcite.cloud_radar AS rd
                  ON rd.radar_id=d.radar_id AND rd.workspace_id=d.workspace_id
                WHERE d.workspace_id=$1 AND d.digest_id=$2
                """,
                workspace_id,
                digest_id,
            )
            if row is None:
                raise NotFoundError("digest not found")
            items = await conn.fetch(
                """
                SELECT signal_id, rank, label, materiality, relevance_score, signal_score,
                       observed_at
                FROM trendcite.cloud_digest_item
                WHERE workspace_id=$1 AND digest_id=$2
                ORDER BY rank
                """,
                workspace_id,
                digest_id,
            )
            result = _digest(row)
            result["body"] = str(row["body"])
            result["items"] = [
                {
                    "signal_id": str(i["signal_id"]),
                    "rank": int(i["rank"]),
                    "label": str(i["label"]),
                    "materiality": str(i["materiality"]),
                    "relevance_score": float(i["relevance_score"]),
                    "signal_score": float(i["signal_score"]),
                    "observed_at": _ts(i["observed_at"]),
                }
                for i in items
            ]
            return result


# ------------------------------------------------------------------------- helpers


async def _insert_watchlist_version(conn: Connection, version: WatchlistVersion) -> None:
    inserted = await conn.fetchval(
        """
        INSERT INTO trendcite.cloud_watchlist_version
            (version_id, watchlist_id, workspace_id, version_number, include_terms,
             exclude_terms, match_mode, matcher_version, created_at, entities, domains)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        ON CONFLICT DO NOTHING
        RETURNING version_id
        """,
        version.version_id,
        version.watchlist_id,
        version.workspace_id,
        version.version_number,
        _json(list(version.include_terms)),
        _json(list(version.exclude_terms)),
        version.match_mode,
        version.matcher_version,
        version.created_at.isoformat(),
        _json(list(version.entities)),
        _json(list(version.domains)),
    )
    if inserted is None:
        raise ConflictError("watchlist changed concurrently; reload and retry")


async def _insert_radar_version(conn: Connection, version: RadarVersion) -> None:
    inserted = await conn.fetchval(
        """
        INSERT INTO trendcite.cloud_radar_version
            (version_id, radar_id, workspace_id, version_number, watchlist_version_ids,
             sources, niche, top, created_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT DO NOTHING
        RETURNING version_id
        """,
        version.version_id,
        version.radar_id,
        version.workspace_id,
        version.version_number,
        _json(list(version.watchlist_version_ids)),
        _json(list(version.sources)),
        _json(list(version.niche)),
        version.top,
        version.created_at.isoformat(),
    )
    if inserted is None:
        raise ConflictError("radar changed concurrently; reload and retry")


async def _pin_latest_versions(
    conn: Connection, workspace_id: str, watchlist_ids: Sequence[str]
) -> tuple[str, ...]:
    """Resolve each watchlist to its latest version *within this workspace*.

    A watchlist id from another workspace resolves to nothing and is reported as not
    found, so a radar can never pin another tenant's configuration.
    """
    wanted = tuple(dict.fromkeys(str(w).strip() for w in watchlist_ids if str(w).strip()))
    if not wanted:
        raise ValidationError("a radar must reference at least one watchlist")
    if len(wanted) > MAX_RADAR_WATCHLISTS:
        raise ValidationError(f"a radar may reference at most {MAX_RADAR_WATCHLISTS} watchlists")
    pinned: list[str] = []
    for watchlist_id in wanted:
        version_id = await conn.fetchval(
            """
            SELECT version_id
            FROM trendcite.cloud_watchlist_version
            WHERE workspace_id=$1 AND watchlist_id=$2
            ORDER BY version_number DESC
            LIMIT 1
            """,
            workspace_id,
            watchlist_id,
        )
        if version_id is None:
            raise NotFoundError("watchlist not found")
        pinned.append(str(version_id))
    return tuple(pinned)


def _customer_sources(sources: Iterable[str]) -> tuple[str, ...]:
    wanted = tuple(dict.fromkeys(str(s).strip().lower() for s in sources if str(s).strip()))
    unknown = [s for s in wanted if s not in CUSTOMER_SOURCES]
    if unknown:
        raise ValidationError("sources must be drawn from: " + ", ".join(CUSTOMER_SOURCES))
    return wanted


def _same_watchlist_content(latest: dict[str, Any], candidate: WatchlistVersion) -> bool:
    return bool(
        latest["include_terms"] == list(candidate.include_terms)
        and latest["exclude_terms"] == list(candidate.exclude_terms)
        and latest["match_mode"] == candidate.match_mode
        and latest["entities"] == list(candidate.entities)
        and latest["domains"] == list(candidate.domains)
    )


def _same_radar_content(latest: dict[str, Any], candidate: RadarVersion) -> bool:
    return bool(
        latest["watchlist_version_ids"] == list(candidate.watchlist_version_ids)
        and latest["sources"] == list(candidate.sources)
        and latest["niche"] == list(candidate.niche)
        and latest["top"] == candidate.top
    )


def _limit(value: int) -> int:
    return max(1, min(int(value), MAX_LIMIT))


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _loads(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if value is None or value == "":
        return []
    return json.loads(str(value))


def _str_list(value: Any) -> list[str]:
    loaded = _loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(x) for x in loaded]


def _ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _ts_or_none(value: Any) -> str | None:
    return None if value is None else _ts(value)


def _version_dict(version: WatchlistVersion) -> dict[str, Any]:
    data = version.to_dict()
    data.pop("workspace_id", None)
    return data


def _radar_version_dict(version: RadarVersion) -> dict[str, Any]:
    data = version.to_dict()
    data.pop("workspace_id", None)
    return data


def _watchlist_version(row: Any) -> dict[str, Any]:
    return {
        "version_id": str(row["version_id"]),
        "watchlist_id": str(row["watchlist_id"]),
        "version_number": int(row["version_number"]),
        "include_terms": _str_list(row["include_terms"]),
        "exclude_terms": _str_list(row["exclude_terms"]),
        "match_mode": str(row["match_mode"]),
        "matcher_version": str(row["matcher_version"]),
        "created_at": _ts(row["created_at"]),
        "entities": _str_list(row["entities"]),
        "domains": _str_list(row["domains"]),
    }


def _radar_version(row: Any) -> dict[str, Any]:
    return {
        "version_id": str(row["version_id"]),
        "radar_id": str(row["radar_id"]),
        "version_number": int(row["version_number"]),
        "watchlist_version_ids": _str_list(row["watchlist_version_ids"]),
        "sources": _str_list(row["sources"]),
        "niche": _str_list(row["niche"]),
        "top": int(row["top"]),
        "created_at": _ts(row["created_at"]),
    }


def _watchlist_summary(row: Any) -> dict[str, Any]:
    latest = None
    if row["version_id"] is not None:
        latest = {
            "version_id": str(row["version_id"]),
            "watchlist_id": str(row["watchlist_id"]),
            "version_number": int(row["version_number"]),
            "include_terms": _str_list(row["include_terms"]),
            "exclude_terms": _str_list(row["exclude_terms"]),
            "match_mode": str(row["match_mode"]),
            "matcher_version": str(row["matcher_version"]),
            "created_at": _ts(row["version_created_at"]),
            "entities": _str_list(row["entities"]),
            "domains": _str_list(row["domains"]),
        }
    return {
        "watchlist_id": str(row["watchlist_id"]),
        "name": str(row["name"]),
        "created_at": _ts(row["created_at"]),
        "latest_version": latest,
    }


def _radar_summary(row: Any) -> dict[str, Any]:
    latest = None
    if row["version_id"] is not None:
        latest = {
            "version_id": str(row["version_id"]),
            "radar_id": str(row["radar_id"]),
            "version_number": int(row["version_number"]),
            "watchlist_version_ids": _str_list(row["watchlist_version_ids"]),
            "sources": _str_list(row["sources"]),
            "niche": _str_list(row["niche"]),
            "top": int(row["top"]),
            "created_at": _ts(row["version_created_at"]),
        }
    return {
        "radar_id": str(row["radar_id"]),
        "name": str(row["name"]),
        "created_at": _ts(row["created_at"]),
        "latest_version": latest,
    }


def _run(row: Any) -> dict[str, Any]:
    return {
        "run_id": str(row["run_id"]),
        "radar_id": str(row["radar_id"]),
        "radar_name": str(row["radar_name"]),
        "radar_version_id": str(row["radar_version_id"]),
        "evaluation_cutoff": _ts(row["evaluation_cutoff"]),
        "status": str(row["status"]),
        "coverage_state": str(row["coverage_state"]),
        "attempt": int(row["attempt"]),
        "signal_count": int(row["signal_count"]),
        "match_count": int(row["match_count"]),
        "error_code": str(row["error_code"]),
        "error_detail": str(row["error_detail"]),
        "started_at": _ts(row["started_at"]),
        "finished_at": _ts_or_none(row["finished_at"]),
    }


def _run_signal(row: Any) -> dict[str, Any]:
    return {
        "signal_id": str(row["signal_id"]),
        "snapshot_id": str(row["snapshot_id"]),
        "relevance": float(row["relevance"]),
        "label": str(row["label"]),
        "related_terms": _str_list(row["related_terms"]),
        "score": float(row["score"]),
        "confidence": str(row["confidence"]),
        "state": str(row["state"]),
        "observation_count": int(row["observation_count"]),
        "story_count": int(row["story_count"]),
        "source_count": int(row["source_count"]),
        "captured_at": _ts(row["captured_at"]),
    }


def _digest(row: Any) -> dict[str, Any]:
    return {
        "digest_id": str(row["digest_id"]),
        "radar_id": str(row["radar_id"]),
        "radar_name": str(row["radar_name"]),
        "digest_date": _ts(row["digest_date"]),
        "window_start": _ts(row["window_start"]),
        "window_end": _ts(row["window_end"]),
        "item_count": int(row["item_count"]),
        "channel": str(row["channel"]),
        "delivery_state": str(row["delivery_state"]),
        "attempt_count": int(row["attempt_count"]),
        "subject": str(row["subject"]),
        "created_at": _ts(row["created_at"]),
        "delivered_at": _ts_or_none(row["delivered_at"]),
    }
