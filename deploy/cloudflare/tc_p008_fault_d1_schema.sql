-- Dedicated TC-P008 D1 only. Never apply to shared or production databases.
CREATE TABLE IF NOT EXISTS tc_p008_fault_commits (
    run_id TEXT PRIMARY KEY NOT NULL,
    phase TEXT NOT NULL CHECK (phase = 'committed')
);
