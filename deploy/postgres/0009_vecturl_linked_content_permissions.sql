-- PostgreSQL-only hardening for canonical linked-content persistence.

REVOKE ALL ON TABLE trendcite.cloud_run_linked_content FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE trendcite.cloud_run_linked_content
    TO trendcite_nonprod_runtime;
