-- 0008_vecturl_linked_content_enrichment
--
-- Supplemental VectURL linked-content evidence for TrendCite nonprod.
-- This table is deliberately separate from EvidenceItem / signal scoring tables.

CREATE TABLE IF NOT EXISTS cloud_linked_content_evidence (
    enrichment_id             TEXT PRIMARY KEY,
    workspace_id              TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    run_id                    TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    signal_id                 TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    source_url                TEXT NOT NULL,
    status                    TEXT NOT NULL CHECK (status IN ('ready', 'failed')),
    bundle_id                 TEXT NOT NULL DEFAULT '',
    text_fragments_json       TEXT NOT NULL DEFAULT '[]',
    provenance_json           TEXT NOT NULL DEFAULT '[]',
    quality_overall           DOUBLE PRECISION NULL,
    actual_cost_micro_usd     BIGINT NOT NULL DEFAULT 0 CHECK (actual_cost_micro_usd >= 0),
    error_code                TEXT NOT NULL DEFAULT '',
    created_at                TEXT NOT NULL,
    UNIQUE (workspace_id, run_id, signal_id, source_url)
);

CREATE INDEX IF NOT EXISTS ix_linked_content_run
    ON cloud_linked_content_evidence (workspace_id, run_id, signal_id);

CREATE INDEX IF NOT EXISTS ix_linked_content_bundle
    ON cloud_linked_content_evidence (bundle_id)
    WHERE bundle_id <> '';

