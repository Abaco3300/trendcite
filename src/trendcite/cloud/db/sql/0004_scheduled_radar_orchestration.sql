-- 0004_scheduled_radar_orchestration
--
-- Additive PC-07 scheduling and resumable orchestration persistence. 0001-0003 remain
-- immutable: this file only creates new tables and indexes, alters no existing column
-- and backfills nothing. A database holding 0001+0002+0003 data upgrades in place; both
-- tables below start empty, and a radar with no schedule row is simply a radar nobody
-- has scheduled, which is the same thing it was before this migration existed.
--
-- Same portable subset as 0001: UTC ISO-8601 text timestamps, booleans as INTEGER 0/1
-- with CHECK constraints, and every identifier supplied by the application
-- (see trendcite.cloud.ids).
--
-- Two tables, because scheduling and execution are two different kinds of truth:
--   * cloud_radar_schedule -- when a radar should run (tenant intent, editable)
--   * cloud_schedule_tick  -- one boundary's execution record (append-then-settle)
-- Neither of them stores what a run found. cloud_schedule_tick.run_id points at
-- cloud_radar_run, which remains the sole authority on execution, so re-planning a
-- boundary can never fabricate a second version of a run's results.

-- -------------------------------------------------------------------------- schedules

-- One schedule per (workspace, radar), held by UNIQUE rather than by application care:
-- a radar on two cadences at once is a radar whose next cutoff nobody can predict.
--
-- utc_offset_minutes is a FIXED offset, not an IANA zone. A DST transition makes
-- "daily at 02:30 local" either ambiguous or non-existent, and an ambiguous boundary
-- is an ambiguous run identity. anchor_at is the resolved first boundary in UTC, so
-- the grid is anchor_at + k * cadence period and needs no wall-clock arithmetic to read.
CREATE TABLE IF NOT EXISTS cloud_radar_schedule (
    schedule_id        TEXT PRIMARY KEY,
    workspace_id       TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id           TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    enabled            INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    cadence            TEXT NOT NULL
                       CHECK (cadence IN ('hourly', 'six_hourly', 'twelve_hourly',
                                          'daily', 'weekly')),
    utc_offset_minutes INTEGER NOT NULL
                       CHECK (utc_offset_minutes >= -720 AND utc_offset_minutes <= 840),
    anchor_at          TEXT NOT NULL,
    -- The catch-up budget is stored per schedule and checked here as well as in the
    -- domain, so no writer -- including a future one -- can persist an unbounded replay.
    max_catch_up       INTEGER NOT NULL CHECK (max_catch_up >= 0 AND max_catch_up <= 50),
    lease_seconds      INTEGER NOT NULL CHECK (lease_seconds >= 1 AND lease_seconds <= 86400),
    max_attempts       INTEGER NOT NULL CHECK (max_attempts >= 1 AND max_attempts <= 10),
    cadence_version    TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    -- Newest boundary already planned. An optimisation only: tick identity is what
    -- actually prevents duplicates, so a stale or NULL watermark costs a re-derivation
    -- and never a second tick.
    last_planned_at    TEXT,
    UNIQUE (workspace_id, radar_id)
);

-- The worker plane's sweep: enabled schedules, oldest watermark first.
CREATE INDEX IF NOT EXISTS ix_radar_schedule_enabled
    ON cloud_radar_schedule (enabled, last_planned_at);

-- ------------------------------------------------------------------------------ ticks

-- One row per (schedule, boundary). UNIQUE (workspace_id, idempotency_key) is the
-- "the same tick is never created twice" guarantee: two planner passes, a restarted
-- worker or an external scheduler firing twice all derive the same key and collide,
-- rather than quietly queueing the same cutoff again.
--
-- status and the lease are separate columns on purpose. status is what has happened to
-- the work; lease_owner/lease_expires_at are a revocable right to be the one doing it.
-- That is what lets an interrupted worker's tick be reclaimed at lease expiry without
-- inventing a "probably dead" status, and what lets a stale worker's late settlement be
-- refused by owner instead of by guesswork.
--
-- run_id is deliberately NOT a foreign key with a NOT NULL constraint: a tick exists
-- before its run does, and a tick that failed before creating one keeps its row.
CREATE TABLE IF NOT EXISTS cloud_schedule_tick (
    tick_id           TEXT PRIMARY KEY,
    schedule_id       TEXT NOT NULL
                      REFERENCES cloud_radar_schedule (schedule_id) ON DELETE CASCADE,
    workspace_id      TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    radar_id          TEXT NOT NULL REFERENCES cloud_radar (radar_id) ON DELETE CASCADE,
    -- The canonical instant this tick asks the radar to be evaluated as of. It is the
    -- same value that becomes RadarRun.evaluation_cutoff, which is why the same
    -- boundary always resolves to the same logical run.
    evaluation_cutoff TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL,
    status            TEXT NOT NULL
                      CHECK (status IN ('pending', 'running', 'succeeded', 'failed',
                                        'skipped')),
    attempt           INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts      INTEGER NOT NULL CHECK (max_attempts >= 1),
    lease_owner       TEXT NOT NULL DEFAULT '',
    lease_expires_at  TEXT,
    run_id            TEXT NOT NULL DEFAULT '',
    skip_reason       TEXT NOT NULL DEFAULT ''
                      CHECK (skip_reason IN ('', 'catch_up_exceeded', 'schedule_disabled',
                                             'attempts_exhausted')),
    error_code        TEXT NOT NULL DEFAULT '',
    error_detail      TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    started_at        TEXT,
    finished_at       TEXT,
    UNIQUE (workspace_id, idempotency_key),
    UNIQUE (schedule_id, evaluation_cutoff)
);

-- The claim sweep: one schedule's unsettled work, oldest cutoff first, so catch-up
-- executes in the order the boundaries occurred.
CREATE INDEX IF NOT EXISTS ix_schedule_tick_claimable
    ON cloud_schedule_tick (workspace_id, status, evaluation_cutoff);

-- Lease reclamation: find running ticks whose owner has gone quiet.
CREATE INDEX IF NOT EXISTS ix_schedule_tick_lease
    ON cloud_schedule_tick (status, lease_expires_at);

-- "What did this schedule do?" answered without a scan.
CREATE INDEX IF NOT EXISTS ix_schedule_tick_schedule
    ON cloud_schedule_tick (workspace_id, schedule_id, evaluation_cutoff);
