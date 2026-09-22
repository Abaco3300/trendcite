"""SQLite persistence for the local TrendCite Cloud Foundation.

SQLite is a development/test adapter only. Domain and application layers depend on
repository protocols, not on sqlite3. The schema itself lives in db/sql/*.sql and is
the migration source of truth.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any

from ..domain import (
    Coverage,
    Match,
    MatchEvaluation,
    Membership,
    Radar,
    RadarRun,
    RadarVersion,
    RunSignal,
    StoredSignal,
    StoredSignalEvaluation,
    UsageEvent,
    Watchlist,
    WatchlistVersion,
    Workspace,
    parse_iso,
)
from ..errors import ConflictError, MigrationError, NotFoundError

_JSON_SEPARATORS = (",", ":")


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=_JSON_SEPARATORS)


def _load(value: str) -> Any:
    return json.loads(value)


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a local Cloud DB with integrity enforcement enabled."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every ordered SQL migration exactly once."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {str(r[0]) for r in conn.execute("SELECT name FROM schema_migrations")}
    sql_dir = Path(__file__).with_name("sql")
    names: list[str] = []
    for path in sorted(sql_dir.glob("*.sql")):
        names.append(path.name)
        if path.name in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (path.name,))
            conn.commit()
        except sqlite3.DatabaseError as exc:
            conn.rollback()
            raise MigrationError(f"migration {path.name} failed") from exc
    return names


class _WorkspaceRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, value: Workspace) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_workspace(workspace_id,slug,name,created_at) VALUES (?,?,?,?)",
                (value.workspace_id, value.slug, value.name, value.created_at.isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("workspace already exists") from exc

    def get(self, workspace_id: str) -> Workspace | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_workspace WHERE workspace_id=?", (workspace_id,)
        ).fetchone()
        return None if row is None else _workspace(row)

    def by_slug(self, slug: str) -> Workspace | None:
        row = self.conn.execute("SELECT * FROM cloud_workspace WHERE slug=?", (slug,)).fetchone()
        return None if row is None else _workspace(row)

    def list_all(self) -> list[Workspace]:
        return [
            _workspace(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_workspace ORDER BY created_at, workspace_id"
            )
        ]


class _MembershipRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, value: Membership) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_membership"
                "(membership_id,workspace_id,principal_id,role,created_at) VALUES (?,?,?,?,?)",
                (
                    value.membership_id,
                    value.workspace_id,
                    value.principal_id,
                    value.role,
                    value.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("membership already exists or workspace is invalid") from exc

    def get(self, workspace_id: str, principal_id: str) -> Membership | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_membership WHERE workspace_id=? AND principal_id=?",
            (workspace_id, principal_id),
        ).fetchone()
        return None if row is None else _membership(row)

    def list_for_workspace(self, workspace_id: str) -> list[Membership]:
        return [
            _membership(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_membership WHERE workspace_id=? ORDER BY created_at",
                (workspace_id,),
            )
        ]


class _WatchlistRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, value: Watchlist) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_watchlist(watchlist_id,workspace_id,name,created_at)"
                " VALUES (?,?,?,?)",
                (value.watchlist_id, value.workspace_id, value.name, value.created_at.isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("watchlist already exists or workspace is invalid") from exc

    def get(self, workspace_id: str, watchlist_id: str) -> Watchlist | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_watchlist WHERE workspace_id=? AND watchlist_id=?",
            (workspace_id, watchlist_id),
        ).fetchone()
        return None if row is None else _watchlist(row)

    def by_name(self, workspace_id: str, name: str) -> Watchlist | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_watchlist WHERE workspace_id=? AND name=?",
            (workspace_id, name),
        ).fetchone()
        return None if row is None else _watchlist(row)

    def list_for_workspace(self, workspace_id: str) -> list[Watchlist]:
        return [
            _watchlist(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_watchlist WHERE workspace_id=? "
                "ORDER BY created_at,watchlist_id",
                (workspace_id,),
            )
        ]

    def add_version(self, value: WatchlistVersion) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_watchlist_version"
                "(version_id,watchlist_id,workspace_id,version_number,include_terms,"
                "exclude_terms,match_mode,matcher_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    value.version_id,
                    value.watchlist_id,
                    value.workspace_id,
                    value.version_number,
                    _dump(value.include_terms),
                    _dump(value.exclude_terms),
                    value.match_mode,
                    value.matcher_version,
                    value.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("watchlist version conflicts with stored state") from exc

    def get_version(self, workspace_id: str, version_id: str) -> WatchlistVersion | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_watchlist_version WHERE workspace_id=? AND version_id=?",
            (workspace_id, version_id),
        ).fetchone()
        return None if row is None else _watchlist_version(row)

    def versions(self, workspace_id: str, watchlist_id: str) -> list[WatchlistVersion]:
        return [
            _watchlist_version(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_watchlist_version WHERE workspace_id=? AND watchlist_id=? "
                "ORDER BY version_number",
                (workspace_id, watchlist_id),
            )
        ]

    def latest_version(self, workspace_id: str, watchlist_id: str) -> WatchlistVersion | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_watchlist_version WHERE workspace_id=? AND watchlist_id=? "
            "ORDER BY version_number DESC LIMIT 1",
            (workspace_id, watchlist_id),
        ).fetchone()
        return None if row is None else _watchlist_version(row)

    def next_version_number(self, workspace_id: str, watchlist_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 FROM cloud_watchlist_version "
            "WHERE workspace_id=? AND watchlist_id=?",
            (workspace_id, watchlist_id),
        ).fetchone()
        return int(row[0])


class _RadarRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, value: Radar) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_radar(radar_id,workspace_id,name,created_at) VALUES (?,?,?,?)",
                (value.radar_id, value.workspace_id, value.name, value.created_at.isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("radar already exists or workspace is invalid") from exc

    def get(self, workspace_id: str, radar_id: str) -> Radar | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_radar WHERE workspace_id=? AND radar_id=?",
            (workspace_id, radar_id),
        ).fetchone()
        return None if row is None else _radar(row)

    def by_name(self, workspace_id: str, name: str) -> Radar | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_radar WHERE workspace_id=? AND name=?",
            (workspace_id, name),
        ).fetchone()
        return None if row is None else _radar(row)

    def list_for_workspace(self, workspace_id: str) -> list[Radar]:
        return [
            _radar(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_radar WHERE workspace_id=? ORDER BY created_at,radar_id",
                (workspace_id,),
            )
        ]

    def add_version(self, value: RadarVersion) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_radar_version"
                "(version_id,radar_id,workspace_id,version_number,watchlist_version_ids,"
                "sources,niche,top,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    value.version_id,
                    value.radar_id,
                    value.workspace_id,
                    value.version_number,
                    _dump(value.watchlist_version_ids),
                    _dump(value.sources),
                    _dump(value.niche),
                    value.top,
                    value.created_at.isoformat(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("radar version conflicts with stored state") from exc

    def get_version(self, workspace_id: str, version_id: str) -> RadarVersion | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_radar_version WHERE workspace_id=? AND version_id=?",
            (workspace_id, version_id),
        ).fetchone()
        return None if row is None else _radar_version(row)

    def versions(self, workspace_id: str, radar_id: str) -> list[RadarVersion]:
        return [
            _radar_version(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_radar_version WHERE workspace_id=? AND radar_id=? "
                "ORDER BY version_number",
                (workspace_id, radar_id),
            )
        ]

    def latest_version(self, workspace_id: str, radar_id: str) -> RadarVersion | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_radar_version WHERE workspace_id=? AND radar_id=? "
            "ORDER BY version_number DESC LIMIT 1",
            (workspace_id, radar_id),
        ).fetchone()
        return None if row is None else _radar_version(row)

    def next_version_number(self, workspace_id: str, radar_id: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(version_number),0)+1 FROM cloud_radar_version "
            "WHERE workspace_id=? AND radar_id=?",
            (workspace_id, radar_id),
        ).fetchone()
        return int(row[0])


class _RunRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def add(self, value: RadarRun) -> None:
        try:
            self.conn.execute(
                "INSERT INTO cloud_radar_run"
                "(run_id,workspace_id,radar_id,radar_version_id,evaluation_cutoff,idempotency_key,"
                "status,coverage_state,attempt,signal_count,match_count,error_code,error_detail,"
                "started_at,finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                _run_values(value),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("radar run already exists or references invalid state") from exc

    def update(self, value: RadarRun) -> None:
        cur = self.conn.execute(
            "UPDATE cloud_radar_run SET status=?,coverage_state=?,attempt=?,signal_count=?,"
            "match_count=?,error_code=?,error_detail=?,started_at=?,finished_at=? "
            "WHERE workspace_id=? AND run_id=?",
            (
                value.status,
                value.coverage_state,
                value.attempt,
                value.signal_count,
                value.match_count,
                value.error_code,
                value.error_detail,
                value.started_at.isoformat(),
                None if value.finished_at is None else value.finished_at.isoformat(),
                value.workspace_id,
                value.run_id,
            ),
        )
        if cur.rowcount != 1:
            raise NotFoundError("radar run not found in workspace")

    def get(self, workspace_id: str, run_id: str) -> RadarRun | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_radar_run WHERE workspace_id=? AND run_id=?",
            (workspace_id, run_id),
        ).fetchone()
        return None if row is None else _run(row)

    def by_idempotency_key(self, workspace_id: str, key: str) -> RadarRun | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_radar_run WHERE workspace_id=? AND idempotency_key=?",
            (workspace_id, key),
        ).fetchone()
        return None if row is None else _run(row)

    def list_for_radar(self, workspace_id: str, radar_id: str) -> list[RadarRun]:
        return [
            _run(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_radar_run WHERE workspace_id=? AND radar_id=? "
                "ORDER BY started_at DESC,run_id DESC",
                (workspace_id, radar_id),
            )
        ]


class _CoverageRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def replace_for_run(self, workspace_id: str, run_id: str, rows: Sequence[Coverage]) -> None:
        self.conn.execute(
            "DELETE FROM cloud_run_coverage WHERE workspace_id=? AND run_id=?",
            (workspace_id, run_id),
        )
        for value in rows:
            if value.workspace_id != workspace_id or value.run_id != run_id:
                raise ConflictError("coverage belongs to another run/workspace")
            self.conn.execute(
                "INSERT INTO cloud_run_coverage"
                "(coverage_id,run_id,workspace_id,source,state,item_count,detail,observed_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (
                    value.coverage_id,
                    value.run_id,
                    value.workspace_id,
                    value.source,
                    value.state,
                    value.item_count,
                    value.detail,
                    value.observed_at.isoformat(),
                ),
            )

    def list_for_run(self, workspace_id: str, run_id: str) -> list[Coverage]:
        return [
            _coverage(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_run_coverage WHERE workspace_id=? AND run_id=? "
                "ORDER BY source",
                (workspace_id, run_id),
            )
        ]


class _SignalRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, value: StoredSignal) -> None:
        existing = self.get(value.signal_id)
        merged = value if existing is None else existing.merged_with(value)
        self.conn.execute(
            "INSERT INTO cloud_signal"
            "(signal_id,signal_key,label,related_terms,first_seen_at,last_seen_at,signal_id_version)"
            " VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(signal_id) DO UPDATE SET label=excluded.label,"
            "related_terms=excluded.related_terms,first_seen_at=excluded.first_seen_at,"
            "last_seen_at=excluded.last_seen_at",
            (
                merged.signal_id,
                merged.signal_key,
                merged.label,
                _dump(merged.related_terms),
                merged.first_seen_at.isoformat(),
                merged.last_seen_at.isoformat(),
                merged.signal_id_version,
            ),
        )

    def get(self, signal_id: str) -> StoredSignal | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_signal WHERE signal_id=?", (signal_id,)
        ).fetchone()
        return None if row is None else _signal(row)

    def record_evaluation(self, value: StoredSignalEvaluation) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO cloud_signal_evaluation"
            "(snapshot_id,signal_id,captured_at,evaluation_version,evidence_set_version,score,"
            "confidence,state,observation_count,story_count,source_count,component_values)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                value.snapshot_id,
                value.signal_id,
                value.captured_at.isoformat(),
                value.evaluation_version,
                value.evidence_set_version,
                value.score,
                value.confidence,
                value.state,
                value.observation_count,
                value.story_count,
                value.source_count,
                _dump(value.component_values),
            ),
        )

    def evaluations(self, signal_id: str) -> list[StoredSignalEvaluation]:
        return [
            _signal_evaluation(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_signal_evaluation WHERE signal_id=? "
                "ORDER BY captured_at,snapshot_id",
                (signal_id,),
            )
        ]

    def link_run(self, value: RunSignal) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO cloud_run_signal"
            "(run_signal_id,run_id,workspace_id,signal_id,snapshot_id,relevance)"
            " VALUES (?,?,?,?,?,?)",
            (
                value.run_signal_id,
                value.run_id,
                value.workspace_id,
                value.signal_id,
                value.snapshot_id,
                value.relevance,
            ),
        )

    def run_signals(self, workspace_id: str, run_id: str) -> list[RunSignal]:
        return [
            _run_signal(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_run_signal WHERE workspace_id=? AND run_id=? "
                "ORDER BY signal_id",
                (workspace_id, run_id),
            )
        ]


class _MatchRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, value: Match) -> None:
        self.conn.execute(
            "INSERT INTO cloud_match"
            "(match_id,workspace_id,radar_id,signal_id,status,strength,watchlist_version_id,"
            "matcher_version,first_matched_at,last_matched_at,last_run_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(workspace_id,radar_id,signal_id) DO UPDATE SET "
            "status=excluded.status,strength=excluded.strength,"
            "watchlist_version_id=excluded.watchlist_version_id,"
            "matcher_version=excluded.matcher_version,last_matched_at=excluded.last_matched_at,"
            "last_run_id=excluded.last_run_id",
            (
                value.match_id,
                value.workspace_id,
                value.radar_id,
                value.signal_id,
                value.status,
                value.strength,
                value.watchlist_version_id,
                value.matcher_version,
                value.first_matched_at.isoformat(),
                value.last_matched_at.isoformat(),
                value.last_run_id,
            ),
        )

    def get(self, workspace_id: str, radar_id: str, signal_id: str) -> Match | None:
        row = self.conn.execute(
            "SELECT * FROM cloud_match WHERE workspace_id=? AND radar_id=? AND signal_id=?",
            (workspace_id, radar_id, signal_id),
        ).fetchone()
        return None if row is None else _match(row)

    def list_for_radar(
        self, workspace_id: str, radar_id: str, *, status: str | None = None
    ) -> list[Match]:
        sql = "SELECT * FROM cloud_match WHERE workspace_id=? AND radar_id=?"
        args: tuple[Any, ...] = (workspace_id, radar_id)
        if status is not None:
            sql += " AND status=?"
            args += (status,)
        sql += " ORDER BY strength DESC,signal_id"
        return [_match(r) for r in self.conn.execute(sql, args)]

    def record_evaluation(self, value: MatchEvaluation) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO cloud_match_evaluation"
            "(evaluation_id,workspace_id,radar_id,run_id,watchlist_version_id,signal_id,"
            "decision,strength,matched_terms,excluded_terms,matched_fields,explanation,"
            "matcher_version,evaluated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                value.evaluation_id,
                value.workspace_id,
                value.radar_id,
                value.run_id,
                value.watchlist_version_id,
                value.signal_id,
                value.decision,
                value.strength,
                _dump(value.matched_terms),
                _dump(value.excluded_terms),
                _dump(value.matched_fields),
                value.explanation,
                value.matcher_version,
                value.evaluated_at.isoformat(),
            ),
        )

    def evaluations_for_run(self, workspace_id: str, run_id: str) -> list[MatchEvaluation]:
        return [
            _match_evaluation(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_match_evaluation WHERE workspace_id=? AND run_id=? "
                "ORDER BY watchlist_version_id,signal_id",
                (workspace_id, run_id),
            )
        ]

    def evaluations_for_signal(
        self, workspace_id: str, radar_id: str, signal_id: str
    ) -> list[MatchEvaluation]:
        return [
            _match_evaluation(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_match_evaluation WHERE workspace_id=? AND radar_id=? "
                "AND signal_id=? ORDER BY evaluated_at,evaluation_id",
                (workspace_id, radar_id, signal_id),
            )
        ]


class _UsageRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record(self, value: UsageEvent) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO cloud_usage_event"
            "(event_id,workspace_id,kind,quantity,occurred_at,run_id,dedupe_key)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                value.event_id,
                value.workspace_id,
                value.kind,
                value.quantity,
                value.occurred_at.isoformat(),
                value.run_id,
                value.dedupe_key,
            ),
        )
        return cur.rowcount == 1

    def list_for_workspace(self, workspace_id: str) -> list[UsageEvent]:
        return [
            _usage(r)
            for r in self.conn.execute(
                "SELECT * FROM cloud_usage_event WHERE workspace_id=? "
                "ORDER BY occurred_at,event_id",
                (workspace_id,),
            )
        ]

    def total(self, workspace_id: str, kind: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM cloud_usage_event "
            "WHERE workspace_id=? AND kind=?",
            (workspace_id, kind),
        ).fetchone()
        return int(row[0])


class SQLiteUnitOfWork:
    """One explicit SQLite transaction implementing all Cloud repository contracts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> SQLiteUnitOfWork:
        self.conn = connect(self.path)
        apply_migrations(self.conn)
        self.conn.execute("BEGIN")
        self.workspaces = _WorkspaceRepo(self.conn)
        self.memberships = _MembershipRepo(self.conn)
        self.watchlists = _WatchlistRepo(self.conn)
        self.radars = _RadarRepo(self.conn)
        self.runs = _RunRepo(self.conn)
        self.coverage = _CoverageRepo(self.conn)
        self.signals = _SignalRepo(self.conn)
        self.matches = _MatchRepo(self.conn)
        self.usage = _UsageRepo(self.conn)
        return self

    def _require_conn(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("unit of work is not active")
        return self.conn

    def commit(self) -> None:
        self._require_conn().commit()

    def rollback(self) -> None:
        self._require_conn().rollback()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        conn = self._require_conn()
        try:
            if exc_type is not None or conn.in_transaction:
                conn.rollback()
        finally:
            conn.close()
            self.conn = None


class SQLiteUnitOfWorkFactory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def __call__(self) -> SQLiteUnitOfWork:
        return SQLiteUnitOfWork(self.path)

    def bootstrap(self) -> list[str]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(self.path)
        try:
            return apply_migrations(conn)
        finally:
            conn.close()


def _workspace(r: sqlite3.Row) -> Workspace:
    return Workspace(
        str(r["workspace_id"]),
        str(r["slug"]),
        str(r["name"]),
        parse_iso(r["created_at"]),
    )


def _membership(r: sqlite3.Row) -> Membership:
    return Membership(
        str(r["membership_id"]),
        str(r["workspace_id"]),
        str(r["principal_id"]),
        str(r["role"]),
        parse_iso(r["created_at"]),
    )


def _watchlist(r: sqlite3.Row) -> Watchlist:
    return Watchlist(
        str(r["watchlist_id"]),
        str(r["workspace_id"]),
        str(r["name"]),
        parse_iso(r["created_at"]),
    )


def _watchlist_version(r: sqlite3.Row) -> WatchlistVersion:
    return WatchlistVersion(
        str(r["version_id"]),
        str(r["watchlist_id"]),
        str(r["workspace_id"]),
        int(r["version_number"]),
        tuple(_load(r["include_terms"])),
        tuple(_load(r["exclude_terms"])),
        str(r["match_mode"]),
        str(r["matcher_version"]),
        parse_iso(r["created_at"]),
    )


def _radar(r: sqlite3.Row) -> Radar:
    return Radar(
        str(r["radar_id"]),
        str(r["workspace_id"]),
        str(r["name"]),
        parse_iso(r["created_at"]),
    )


def _radar_version(r: sqlite3.Row) -> RadarVersion:
    return RadarVersion(
        str(r["version_id"]),
        str(r["radar_id"]),
        str(r["workspace_id"]),
        int(r["version_number"]),
        tuple(_load(r["watchlist_version_ids"])),
        tuple(_load(r["sources"])),
        tuple(_load(r["niche"])),
        int(r["top"]),
        parse_iso(r["created_at"]),
    )


def _run_values(v: RadarRun) -> tuple[Any, ...]:
    return (
        v.run_id,
        v.workspace_id,
        v.radar_id,
        v.radar_version_id,
        v.evaluation_cutoff.isoformat(),
        v.idempotency_key,
        v.status,
        v.coverage_state,
        v.attempt,
        v.signal_count,
        v.match_count,
        v.error_code,
        v.error_detail,
        v.started_at.isoformat(),
        None if v.finished_at is None else v.finished_at.isoformat(),
    )


def _run(r: sqlite3.Row) -> RadarRun:
    return RadarRun(
        str(r["run_id"]),
        str(r["workspace_id"]),
        str(r["radar_id"]),
        str(r["radar_version_id"]),
        parse_iso(r["evaluation_cutoff"]),
        str(r["idempotency_key"]),
        str(r["status"]),
        str(r["coverage_state"]),
        int(r["attempt"]),
        int(r["signal_count"]),
        int(r["match_count"]),
        str(r["error_code"]),
        str(r["error_detail"]),
        parse_iso(r["started_at"]),
        None if r["finished_at"] is None else parse_iso(r["finished_at"]),
    )


def _coverage(r: sqlite3.Row) -> Coverage:
    return Coverage(
        str(r["coverage_id"]),
        str(r["run_id"]),
        str(r["workspace_id"]),
        str(r["source"]),
        str(r["state"]),
        int(r["item_count"]),
        str(r["detail"]),
        parse_iso(r["observed_at"]),
    )


def _signal(r: sqlite3.Row) -> StoredSignal:
    return StoredSignal(
        str(r["signal_id"]),
        str(r["signal_key"]),
        str(r["label"]),
        tuple(_load(r["related_terms"])),
        parse_iso(r["first_seen_at"]),
        parse_iso(r["last_seen_at"]),
        str(r["signal_id_version"]),
    )


def _signal_evaluation(r: sqlite3.Row) -> StoredSignalEvaluation:
    return StoredSignalEvaluation(
        str(r["snapshot_id"]),
        str(r["signal_id"]),
        parse_iso(r["captured_at"]),
        str(r["evaluation_version"]),
        str(r["evidence_set_version"]),
        float(r["score"]),
        str(r["confidence"]),
        str(r["state"]),
        int(r["observation_count"]),
        int(r["story_count"]),
        int(r["source_count"]),
        dict(_load(r["component_values"])),
    )


def _run_signal(r: sqlite3.Row) -> RunSignal:
    return RunSignal(
        str(r["run_signal_id"]),
        str(r["run_id"]),
        str(r["workspace_id"]),
        str(r["signal_id"]),
        str(r["snapshot_id"]),
        float(r["relevance"]),
    )


def _match(r: sqlite3.Row) -> Match:
    return Match(
        str(r["match_id"]),
        str(r["workspace_id"]),
        str(r["radar_id"]),
        str(r["signal_id"]),
        str(r["status"]),
        float(r["strength"]),
        str(r["watchlist_version_id"]),
        str(r["matcher_version"]),
        parse_iso(r["first_matched_at"]),
        parse_iso(r["last_matched_at"]),
        str(r["last_run_id"]),
    )


def _match_evaluation(r: sqlite3.Row) -> MatchEvaluation:
    return MatchEvaluation(
        str(r["evaluation_id"]),
        str(r["workspace_id"]),
        str(r["radar_id"]),
        str(r["run_id"]),
        str(r["watchlist_version_id"]),
        str(r["signal_id"]),
        str(r["decision"]),
        float(r["strength"]),
        tuple(_load(r["matched_terms"])),
        tuple(_load(r["excluded_terms"])),
        tuple(_load(r["matched_fields"])),
        str(r["explanation"]),
        str(r["matcher_version"]),
        parse_iso(r["evaluated_at"]),
    )


def _usage(r: sqlite3.Row) -> UsageEvent:
    return UsageEvent(
        str(r["event_id"]),
        str(r["workspace_id"]),
        str(r["kind"]),
        int(r["quantity"]),
        parse_iso(r["occurred_at"]),
        str(r["run_id"]),
        str(r["dedupe_key"]),
    )
