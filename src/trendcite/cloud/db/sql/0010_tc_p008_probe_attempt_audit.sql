-- TC-P008: nonprod synthetic physical Queue attempt audit, no customer payloads.
-- Run only against approved nonprod schema via an explicit migration procedure.
CREATE TABLE IF NOT EXISTS cloud_queue_probe_attempt (
    attempt_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace(workspace_id) ON DELETE CASCADE,
    logical_id TEXT NOT NULL,
    queue_message_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    outcome TEXT NOT NULL CHECK (outcome IN ('received','duplicate_ack','postcommit_retry')),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, logical_id, queue_message_id, attempt, outcome),
    CHECK (logical_id LIKE 'tc-p008-postcommit-%')
);
CREATE INDEX IF NOT EXISTS ix_cloud_queue_probe_attempt_identity
    ON cloud_queue_probe_attempt(workspace_id, logical_id, attempt);
