-- 0007_full_automation_readiness
--
-- Durable operational evidence for autonomous recovery and queue failure visibility.
-- Additive only: existing scheduler, queue and execution tables remain authoritative.

CREATE TABLE IF NOT EXISTS cloud_automation_heartbeat (
    component_key TEXT PRIMARY KEY,
    observed_at   TEXT NOT NULL,
    detail_json   TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS cloud_recovery_action (
    action_id     TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    tick_id       TEXT NOT NULL REFERENCES cloud_schedule_tick (tick_id) ON DELETE CASCADE,
    attempt       INTEGER NOT NULL CHECK (attempt >= 0),
    action        TEXT NOT NULL
                  CHECK (action IN ('pending_requeue',
                                    'failed_requeue',
                                    'expired_lease_requeue',
                                    'expired_final_terminal')),
    reason        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    UNIQUE (workspace_id, tick_id, attempt, action)
);

CREATE INDEX IF NOT EXISTS ix_recovery_action_workspace
    ON cloud_recovery_action (workspace_id, created_at);

CREATE TABLE IF NOT EXISTS cloud_queue_failure_event (
    failure_id       TEXT PRIMARY KEY,
    workspace_id     TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    logical_id       TEXT NOT NULL,
    kind             TEXT NOT NULL,
    queue_message_id TEXT NOT NULL,
    attempt          INTEGER NOT NULL CHECK (attempt >= 1),
    max_attempts     INTEGER NOT NULL CHECK (max_attempts >= 1),
    error_type       TEXT NOT NULL,
    observed_at      TEXT NOT NULL,
    UNIQUE (queue_message_id, attempt)
);

CREATE INDEX IF NOT EXISTS ix_queue_failure_workspace
    ON cloud_queue_failure_event (workspace_id, observed_at);

CREATE INDEX IF NOT EXISTS ix_queue_failure_attempts
    ON cloud_queue_failure_event (workspace_id, attempt, max_attempts);
