-- 0006_entitlements_metering
--
-- Noncommercial entitlement control for TrendCite Pro. Existing cloud_usage_event
-- remains the metering ledger; this migration only adds plan policy and workspace
-- assignment state. No billing, checkout or payment-provider data belongs here.

CREATE TABLE IF NOT EXISTS cloud_entitlement_plan (
    plan_key      TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    capabilities  TEXT NOT NULL,
    quotas        TEXT NOT NULL,
    commercial    INTEGER NOT NULL DEFAULT 0 CHECK (commercial IN (0, 1)),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cloud_workspace_entitlement (
    entitlement_id TEXT PRIMARY KEY,
    workspace_id   TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    plan_key       TEXT NOT NULL REFERENCES cloud_entitlement_plan (plan_key),
    effective_from TEXT NOT NULL,
    effective_until TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    UNIQUE (workspace_id, effective_from)
);

CREATE INDEX IF NOT EXISTS ix_workspace_entitlement_effective
    ON cloud_workspace_entitlement (workspace_id, effective_from, effective_until);

CREATE INDEX IF NOT EXISTS ix_usage_period
    ON cloud_usage_event (workspace_id, kind, occurred_at);
