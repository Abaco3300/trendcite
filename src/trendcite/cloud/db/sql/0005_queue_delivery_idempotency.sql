-- 0005_queue_delivery_idempotency
--
-- Durable Queue delivery ledger for the Cloudflare worker plane.
-- A queue is at-least-once; this table makes one tenant/logical delivery exactly one
-- persisted effect. The payload itself is not stored here, only the identity needed
-- to reject a retry before downstream side effects are attempted.

CREATE TABLE IF NOT EXISTS cloud_queue_delivery (
    delivery_id  TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    logical_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    UNIQUE (workspace_id, logical_id)
);

CREATE INDEX IF NOT EXISTS ix_queue_delivery_workspace
    ON cloud_queue_delivery (workspace_id, first_seen_at);

[executed on device: LAPTOP-JOSEMILE (056f59c1-dbac-4f47-875e-044865a705aa)]