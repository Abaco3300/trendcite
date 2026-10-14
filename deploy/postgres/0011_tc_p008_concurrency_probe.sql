-- Hosted synthetic Queue concurrency evidence; private nonprod role only.
CREATE TABLE IF NOT EXISTS trendcite.cloud_queue_probe_invocation (
  invocation_id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES trendcite.cloud_workspace(workspace_id) ON DELETE CASCADE,
  logical_id TEXT NOT NULL CHECK (logical_id LIKE 'tc-p008-concurrency-%'),
  queue_message_id TEXT NOT NULL,
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  finished_at TIMESTAMPTZ,
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX IF NOT EXISTS ix_cloud_queue_probe_invocation_logical
  ON trendcite.cloud_queue_probe_invocation(logical_id,started_at);
REVOKE ALL ON TABLE trendcite.cloud_queue_probe_invocation FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE trendcite.cloud_queue_probe_invocation TO trendcite_nonprod_runtime;
