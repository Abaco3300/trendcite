-- 0001_cloud_foundation
--
-- The TrendCite Cloud Foundation schema. This file is the source of truth for the
-- relational shape; the Python domain mirrors it, never the other way round.
--
-- Written in the subset SQLite and PostgreSQL agree on, so the same file bootstraps a
-- local development database and a managed one:
--   * timestamps are TEXT holding UTC ISO-8601 (lexical order == chronological order)
--   * booleans and enums are TEXT/INTEGER with CHECK constraints, not engine-specific
--     BOOLEAN or ENUM types
--   * lists and maps are TEXT holding JSON (a PostgreSQL deployment may later widen
--     these columns to JSONB without changing their meaning)
--   * no AUTOINCREMENT, no SERIAL, no engine-specific functions: every identifier is
--     supplied by the application (see trendcite.cloud.ids)
--
-- Tenancy: every tenant-scoped table carries workspace_id and cascades from
-- cloud_workspace. cloud_signal and cloud_signal_evaluation deliberately do NOT carry
-- workspace_id -- public-source signals are globally canonical. A tenant's view of a
-- signal is cloud_run_signal, which does.

-- --------------------------------------------------------------------- tenant roots

CREATE TABLE IF NOT EXISTS cloud_workspace (
    workspace_id TEXT PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cloud_membership (
    membership_id TEXT PRIMARY KEY,
    workspace_id  TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    principal_id  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    created_at    TEXT NOT NULL,
    UNIQUE (workspace_id, principal_id)
);

CREATE INDEX IF NOT EXISTS ix_membership_workspace ON cloud_membership (workspace_id);

-- ------------------------------------------------------------------------ watchlists

CREATE TABLE IF NOT EXISTS cloud_watchlist (
    watchlist_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, name)
);

-- Immutable. There is no UPDATE path to this table anywhere in the application: an
-- edit appends the next version_number, so a radar pinned to version 2 keeps meaning
-- what it meant when it was pinned.
CREATE TABLE IF NOT EXISTS cloud_watchlist_version (
    version_id      TEXT PRIMARY KEY,
    watchlist_id    TEXT NOT NULL REFERENCES cloud_watchlist (watchlist_id) ON DELETE CASCADE,
    workspace_id    TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL CHECK (version_number >= 1),
    include_terms   TEXT NOT NULL,
    exclude_terms   TEXT NOT NULL,
    match_mode      TEXT NOT NULL CHECK (match_mode IN ('any', 'all')),
    matcher_version TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (watchlist_id, version_number)
);

CREATE INDEX IF NOT EXISTS ix_watchlist_version_scope
    ON cloud_watchlist_version (workspace_id, watchlist_id);

-- ---------------------------------------------------------------------------- radars

CREATE TABLE IF NOT EXISTS cloud_radar (
    radar_id     TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, name)
);

-- Immutable, like watchlist versions. watchlist_version_ids is a JSON array of exact
-- cloud_watchlist_version.version_id values: the pin is to versions, never to names.
CREATE TABLE IF NOT EXISTS cloud_radar_version (
    version_id            TEXT PRIMARY KEY,
    radar_id              TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    workspace_id          TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    version_number        INTEGER NOT NULL CHECK (version_number >= 1),
    watchlist_version_ids TEXT NOT NULL,
    sources               TEXT NOT NULL,
    niche                 TEXT NOT NULL,
    top                   INTEGER NOT NULL CHECK (top >= 1),
    created_at            TEXT NOT NULL,
    UNIQUE (radar_id, version_number)
);

CREATE INDEX IF NOT EXISTS ix_radar_version_scope
    ON cloud_radar_version (workspace_id, radar_id);

-- ------------------------------------------------------------------------------ runs

-- The UNIQUE (workspace_id, idempotency_key) constraint is the idempotency guarantee.
-- It is held by the database, not by application logic, so two concurrent submissions
-- of the same pinned request cannot both create a run however they interleave.
CREATE TABLE IF NOT EXISTS cloud_radar_run (
    run_id            TEXT PRIMARY KEY,
    workspace_id      TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id          TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    radar_version_id  TEXT NOT NULL REFERENCES cloud_radar_version (version_id),
    evaluation_cutoff TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL,
    status            TEXT NOT NULL
                      CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
    coverage_state    TEXT NOT NULL
                      CHECK (coverage_state IN ('unknown', 'complete', 'degraded', 'unavailable')),
    attempt           INTEGER NOT NULL CHECK (attempt >= 1),
    signal_count      INTEGER NOT NULL DEFAULT 0,
    match_count       INTEGER NOT NULL DEFAULT 0,
    error_code        TEXT NOT NULL DEFAULT '',
    error_detail      TEXT NOT NULL DEFAULT '',
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    UNIQUE (workspace_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_radar_run_scope
    ON cloud_radar_run (workspace_id, radar_id, started_at);

-- Per-source coverage. state='ok' with item_count=0 means "the source answered and
-- had nothing"; state='failed' means "the source did not answer". Only the first one
-- is evidence of no activity.
CREATE TABLE IF NOT EXISTS cloud_run_coverage (
    coverage_id  TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    source       TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('ok', 'degraded', 'failed', 'skipped')),
    item_count   INTEGER NOT NULL CHECK (item_count >= 0),
    detail       TEXT NOT NULL DEFAULT '',
    observed_at  TEXT NOT NULL,
    UNIQUE (run_id, source)
);

-- ---------------------------------------------------------- globally canonical signals

-- No workspace_id, by design. signal_id is the core trendcite.signal id, reused
-- verbatim: Cloud stores signals, it does not mint or re-score them.
CREATE TABLE IF NOT EXISTS cloud_signal (
    signal_id         TEXT PRIMARY KEY,
    signal_key        TEXT NOT NULL,
    label             TEXT NOT NULL,
    related_terms     TEXT NOT NULL,
    first_seen_at     TEXT NOT NULL,
    last_seen_at      TEXT NOT NULL,
    signal_id_version TEXT NOT NULL
);

-- Append-oriented and content-addressed: snapshot_id is the core snapshot id, so the
-- same evaluation recorded twice is one row, and no evaluation is ever updated.
CREATE TABLE IF NOT EXISTS cloud_signal_evaluation (
    snapshot_id          TEXT PRIMARY KEY,
    signal_id            TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    captured_at          TEXT NOT NULL,
    evaluation_version   TEXT NOT NULL,
    evidence_set_version TEXT NOT NULL,
    score                DOUBLE PRECISION NOT NULL,
    confidence           TEXT NOT NULL,
    state                TEXT NOT NULL,
    observation_count    INTEGER NOT NULL,
    story_count          INTEGER NOT NULL,
    source_count         INTEGER NOT NULL,
    component_values     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_signal_evaluation_signal
    ON cloud_signal_evaluation (signal_id, captured_at);

-- The tenant-scoped edge into the global signal graph. relevance is the tenant's
-- opinion of a public signal and lives here, never on cloud_signal.
CREATE TABLE IF NOT EXISTS cloud_run_signal (
    run_signal_id TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    workspace_id  TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    signal_id     TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    snapshot_id   TEXT NOT NULL
                  REFERENCES cloud_signal_evaluation (snapshot_id) ON DELETE CASCADE,
    relevance     DOUBLE PRECISION NOT NULL,
    UNIQUE (run_id, signal_id)
);

CREATE INDEX IF NOT EXISTS ix_run_signal_scope ON cloud_run_signal (workspace_id, run_id);

-- --------------------------------------------------------------------------- matching

-- Current state: one row per (workspace, radar, signal), updated in place.
CREATE TABLE IF NOT EXISTS cloud_match (
    match_id             TEXT PRIMARY KEY,
    workspace_id         TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id             TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    signal_id            TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    status               TEXT NOT NULL CHECK (status IN ('active', 'dropped')),
    strength             DOUBLE PRECISION NOT NULL,
    watchlist_version_id TEXT NOT NULL,
    matcher_version      TEXT NOT NULL,
    first_matched_at     TEXT NOT NULL,
    last_matched_at      TEXT NOT NULL,
    last_run_id          TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    UNIQUE (workspace_id, radar_id, signal_id)
);

CREATE INDEX IF NOT EXISTS ix_match_scope ON cloud_match (workspace_id, radar_id, status);

-- History: append-only, one row per (run, watchlist version, signal). Never updated,
-- which is what makes "why did this match in March?" answerable in April.
CREATE TABLE IF NOT EXISTS cloud_match_evaluation (
    evaluation_id        TEXT PRIMARY KEY,
    workspace_id         TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id             TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    run_id               TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    watchlist_version_id TEXT NOT NULL
                         REFERENCES cloud_watchlist_version (version_id) ON DELETE CASCADE,
    signal_id            TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    decision             TEXT NOT NULL
                         CHECK (decision IN ('matched', 'no_match', 'excluded')),
    strength             DOUBLE PRECISION NOT NULL,
    matched_terms        TEXT NOT NULL,
    excluded_terms       TEXT NOT NULL,
    matched_fields       TEXT NOT NULL,
    explanation          TEXT NOT NULL,
    matcher_version      TEXT NOT NULL,
    evaluated_at         TEXT NOT NULL,
    UNIQUE (run_id, watchlist_version_id, signal_id)
);

CREATE INDEX IF NOT EXISTS ix_match_evaluation_run
    ON cloud_match_evaluation (workspace_id, run_id);

CREATE INDEX IF NOT EXISTS ix_match_evaluation_signal
    ON cloud_match_evaluation (workspace_id, radar_id, signal_id, evaluated_at);

-- ---------------------------------------------------------------------------- metering

-- UNIQUE (workspace_id, dedupe_key) is the metering guarantee: a retried run derives
-- the same dedupe keys, so it cannot bill the tenant twice for one logical unit.
CREATE TABLE IF NOT EXISTS cloud_usage_event (
    event_id     TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    quantity     INTEGER NOT NULL CHECK (quantity >= 0),
    occurred_at  TEXT NOT NULL,
    run_id       TEXT NOT NULL DEFAULT '',
    dedupe_key   TEXT NOT NULL,
    UNIQUE (workspace_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS ix_usage_scope ON cloud_usage_event (workspace_id, kind);
