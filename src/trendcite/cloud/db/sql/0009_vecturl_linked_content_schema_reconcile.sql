-- 0009_vecturl_linked_content_schema_reconcile
--
-- Forward-only reconciliation: cloud_run_linked_content is the canonical
-- supplemental VectURL persistence table. The transient 0008 duplicate is removed.

CREATE TABLE IF NOT EXISTS cloud_run_linked_content (
    linked_content_id                TEXT PRIMARY KEY,
    workspace_id                     TEXT NOT NULL REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    run_id                           TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    signal_id                        TEXT NOT NULL REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    bundle_id                        TEXT NOT NULL,
    source_url                       TEXT NOT NULL,
    text_fragments                   TEXT NOT NULL,
    provenance_json                  TEXT NOT NULL,
    quality_overall                  REAL NULL,
    quality_completeness             REAL NULL,
    quality_provenance_coverage      REAL NULL,
    fulfilled_capabilities           TEXT NOT NULL,
    missing_capabilities             TEXT NOT NULL,
    actual_cost_micro_usd            INTEGER NULL,
    captured_at                      TEXT NOT NULL,
    UNIQUE (run_id, signal_id, source_url)
);

CREATE INDEX IF NOT EXISTS ix_run_linked_content_workspace_run
    ON cloud_run_linked_content (workspace_id, run_id);

CREATE INDEX IF NOT EXISTS ix_run_linked_content_signal
    ON cloud_run_linked_content (signal_id, captured_at);

DROP TABLE IF EXISTS cloud_linked_content_evidence;
