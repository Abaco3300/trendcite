-- 0008_vecturl_linked_content_runtime
--
-- Supplemental VectURL linked-content persistence. This table is deliberately
-- separate from EvidenceItem, signal evaluation, relevance, matching and scoring.

CREATE TABLE IF NOT EXISTS cloud_run_linked_content (
    linked_content_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    bundle_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    text_fragments TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    quality_overall REAL,
    quality_completeness REAL,
    quality_provenance_coverage REAL,
    fulfilled_capabilities TEXT NOT NULL,
    missing_capabilities TEXT NOT NULL,
    actual_cost_micro_usd INTEGER,
    captured_at TEXT NOT NULL,
    UNIQUE (run_id, signal_id, source_url)
);

CREATE INDEX IF NOT EXISTS ix_run_linked_content_workspace_run
    ON cloud_run_linked_content (workspace_id, run_id);

CREATE INDEX IF NOT EXISTS ix_run_linked_content_signal
    ON cloud_run_linked_content (signal_id, captured_at);
