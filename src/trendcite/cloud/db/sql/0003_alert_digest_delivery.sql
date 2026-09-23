-- 0003_alert_digest_delivery
--
-- Additive PC-06B alerting, digest and delivery persistence. 0001 and 0002 remain
-- immutable: this file only creates new tables and indexes, and alters nothing that
-- an earlier migration wrote. A database holding only 0001+0002 data upgrades in
-- place with no rewrite and no backfill -- every table below starts empty, and every
-- read path treats "no row" as the documented default rather than as missing data.
--
-- Same portable subset as 0001: UTC ISO-8601 text timestamps, JSON in TEXT, booleans
-- as INTEGER 0/1 with CHECK constraints, and every identifier supplied by the
-- application (see trendcite.cloud.ids).
--
-- Four kinds of truth are kept in four places on purpose, and the schema is what
-- enforces it:
--   * cloud_alert_candidate  -- what we judged, including everything we suppressed
--   * cloud_alert            -- what we decided to send
--   * cloud_delivery_attempt -- what a provider actually did, append-only
--   * cloud_alert_baseline   -- the last state we successfully *told the tenant*
-- A failed send therefore cannot move a baseline, because they are different tables
-- written at different moments by different code paths.

-- --------------------------------------------------------------------------- policy

-- One row per (workspace, radar). Absence is not "alerting is off": a radar with no
-- row uses the documented defaults, so an untouched radar and a radar explicitly set
-- to the defaults behave identically.
CREATE TABLE IF NOT EXISTS cloud_alert_policy (
    policy_id             TEXT PRIMARY KEY,
    workspace_id          TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id              TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    enabled               INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    immediate_alerts      INTEGER NOT NULL CHECK (immediate_alerts IN (0, 1)),
    daily_digest          INTEGER NOT NULL CHECK (daily_digest IN (0, 1)),
    min_relevance         DOUBLE PRECISION NOT NULL
                          CHECK (min_relevance >= 0 AND min_relevance <= 100),
    min_materiality       TEXT NOT NULL
                          CHECK (min_materiality IN ('none', 'minor', 'material', 'major')),
    cooldown_hours        DOUBLE PRECISION NOT NULL CHECK (cooldown_hours >= 0),
    digest_max_items      INTEGER NOT NULL CHECK (digest_max_items >= 1),
    max_delivery_attempts INTEGER NOT NULL CHECK (max_delivery_attempts >= 1),
    channel               TEXT NOT NULL,
    policy_version        TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE (workspace_id, radar_id)
);

-- ------------------------------------------------------------------------- baseline

-- The last state a tenant was actually told about, per (workspace, watchlist, signal).
-- Materiality compares against this row and not against the previous run, which is
-- what stops slow drift from being re-alerted every day. It is written only after a
-- successful delivery attempt.
CREATE TABLE IF NOT EXISTS cloud_alert_baseline (
    baseline_id         TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    watchlist_id        TEXT NOT NULL REFERENCES cloud_watchlist (watchlist_id) ON DELETE CASCADE,
    signal_id           TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    alert_id            TEXT NOT NULL,
    signal_snapshot_id  TEXT NOT NULL,
    signal_score        DOUBLE PRECISION NOT NULL,
    relevance_score     DOUBLE PRECISION NOT NULL,
    lifecycle_state     TEXT NOT NULL DEFAULT '',
    velocity            DOUBLE PRECISION,
    source_count        INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    counterevidence     TEXT NOT NULL DEFAULT '[]',
    delivered_at        TEXT NOT NULL,
    materiality_version TEXT NOT NULL,
    UNIQUE (workspace_id, watchlist_id, signal_id)
);

-- ------------------------------------------------------------------------ candidates

-- Every judged opportunity to interrupt a tenant, suppressed ones included. The
-- UNIQUE constraint below is the deduplication guarantee: one (subject, snapshot,
-- materiality version) is one candidate however many runs reach it, so a retried run
-- re-decides rather than re-alerts.
CREATE TABLE IF NOT EXISTS cloud_alert_candidate (
    candidate_id        TEXT PRIMARY KEY,
    workspace_id        TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id            TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    watchlist_id        TEXT NOT NULL REFERENCES cloud_watchlist (watchlist_id) ON DELETE CASCADE,
    signal_id           TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    signal_snapshot_id  TEXT NOT NULL
                        REFERENCES cloud_signal_evaluation (snapshot_id) ON DELETE CASCADE,
    run_id              TEXT NOT NULL DEFAULT '',
    subject_key         TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('qualified', 'suppressed')),
    reason              TEXT NOT NULL
                        CHECK (reason IN ('qualified', 'delivery_disabled', 'muted',
                                          'dismissed', 'below_relevance',
                                          'below_materiality', 'duplicate', 'cooldown')),
    label               TEXT NOT NULL DEFAULT '',
    relevance_score     DOUBLE PRECISION NOT NULL,
    signal_score        DOUBLE PRECISION NOT NULL,
    lifecycle_state     TEXT NOT NULL DEFAULT '',
    velocity            DOUBLE PRECISION,
    source_count        INTEGER NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    counterevidence     TEXT NOT NULL DEFAULT '[]',
    materiality         TEXT NOT NULL
                        CHECK (materiality IN ('none', 'minor', 'material', 'major')),
    materiality_version TEXT NOT NULL,
    evaluation_json     TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    UNIQUE (workspace_id, watchlist_id, signal_id, signal_snapshot_id, materiality_version)
);

-- The digest's daily window query: one radar, one day, ranked.
CREATE INDEX IF NOT EXISTS ix_alert_candidate_window
    ON cloud_alert_candidate (workspace_id, radar_id, observed_at);

-- "Why was I not told about this signal?" answered without a scan.
CREATE INDEX IF NOT EXISTS ix_alert_candidate_subject
    ON cloud_alert_candidate (workspace_id, subject_key, observed_at);

-- ---------------------------------------------------------------------------- alerts

-- One Alert per qualified candidate, held by UNIQUE (candidate_id) rather than by
-- application care. delivery_state is bookkeeping about the send, never a claim about
-- the signal: an alert that failed to deliver is still a judgement that was correctly
-- made, and it keeps its row.
CREATE TABLE IF NOT EXISTS cloud_alert (
    alert_id         TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id         TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    watchlist_id     TEXT NOT NULL REFERENCES cloud_watchlist (watchlist_id) ON DELETE CASCADE,
    signal_id        TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    signal_snapshot_id TEXT NOT NULL,
    candidate_id     TEXT NOT NULL
                     REFERENCES cloud_alert_candidate (candidate_id) ON DELETE CASCADE,
    subject_key      TEXT NOT NULL,
    materiality      TEXT NOT NULL
                     CHECK (materiality IN ('none', 'minor', 'material', 'major')),
    relevance_score  DOUBLE PRECISION NOT NULL,
    signal_score     DOUBLE PRECISION NOT NULL,
    channel          TEXT NOT NULL,
    delivery_state   TEXT NOT NULL
                     CHECK (delivery_state IN ('pending', 'delivered', 'failed')),
    attempt_count    INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    delivered_at     TEXT,
    UNIQUE (candidate_id)
);

CREATE INDEX IF NOT EXISTS ix_alert_scope
    ON cloud_alert (workspace_id, radar_id, created_at);

CREATE INDEX IF NOT EXISTS ix_alert_subject
    ON cloud_alert (workspace_id, subject_key, delivery_state);

-- --------------------------------------------------------------------------- digests

-- One digest per radar per UTC day. UNIQUE (workspace_id, radar_id, digest_date) is
-- the idempotency guarantee: rebuilding Tuesday updates Tuesday. An empty day is
-- never written at all, so no row here is ever a digest with nothing in it.
CREATE TABLE IF NOT EXISTS cloud_digest (
    digest_id        TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id         TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    digest_date      TEXT NOT NULL,
    window_start     TEXT NOT NULL,
    window_end       TEXT NOT NULL,
    item_count       INTEGER NOT NULL CHECK (item_count >= 1),
    channel          TEXT NOT NULL,
    delivery_state   TEXT NOT NULL
                     CHECK (delivery_state IN ('pending', 'delivered', 'failed')),
    attempt_count    INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    subject          TEXT NOT NULL,
    body             TEXT NOT NULL,
    renderer_version TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    delivered_at     TEXT,
    UNIQUE (workspace_id, radar_id, digest_date)
);

-- UNIQUE (digest_id, signal_id) is the "one signal appears at most once" rule, held
-- by the database rather than by whoever writes the ranking loop.
CREATE TABLE IF NOT EXISTS cloud_digest_item (
    item_id            TEXT PRIMARY KEY,
    digest_id          TEXT NOT NULL REFERENCES cloud_digest (digest_id) ON DELETE CASCADE,
    workspace_id       TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    signal_id          TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    candidate_id       TEXT NOT NULL
                       REFERENCES cloud_alert_candidate (candidate_id) ON DELETE CASCADE,
    signal_snapshot_id TEXT NOT NULL,
    rank               INTEGER NOT NULL CHECK (rank >= 1),
    label              TEXT NOT NULL DEFAULT '',
    materiality        TEXT NOT NULL
                       CHECK (materiality IN ('none', 'minor', 'material', 'major')),
    relevance_score    DOUBLE PRECISION NOT NULL,
    signal_score       DOUBLE PRECISION NOT NULL,
    observed_at        TEXT NOT NULL,
    UNIQUE (digest_id, signal_id)
);

CREATE INDEX IF NOT EXISTS ix_digest_item_scope
    ON cloud_digest_item (workspace_id, digest_id, rank);

-- ------------------------------------------------------------------ delivery attempts

-- Append-only, and deliberately not a column on the Alert. One Alert may have many
-- attempts; attempt 3 succeeding does not rewrite attempts 1 and 2, because "it went
-- out on the third try" is a different fact from "it went out". target_id is not a
-- foreign key: one table records attempts for both alerts and digests, and target_kind
-- says which, so adding a third deliverable later needs no schema change.
CREATE TABLE IF NOT EXISTS cloud_delivery_attempt (
    attempt_id         TEXT PRIMARY KEY,
    workspace_id       TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    target_kind        TEXT NOT NULL CHECK (target_kind IN ('alert', 'digest')),
    target_id          TEXT NOT NULL,
    attempt_number     INTEGER NOT NULL CHECK (attempt_number >= 1),
    channel            TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    provider           TEXT NOT NULL DEFAULT '',
    provider_reference TEXT NOT NULL DEFAULT '',
    detail             TEXT NOT NULL DEFAULT '',
    attempted_at       TEXT NOT NULL,
    UNIQUE (workspace_id, target_kind, target_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS ix_delivery_attempt_target
    ON cloud_delivery_attempt (workspace_id, target_kind, target_id, attempt_number);
