-- PostgreSQL-only hardening for 0008 linked-content enrichment.
-- Kept outside the portable SQLite-compatible application migration.

REVOKE ALL ON TABLE trendcite.cloud_linked_content_evidence FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE trendcite.cloud_linked_content_evidence
    TO trendcite_nonprod_runtime;
