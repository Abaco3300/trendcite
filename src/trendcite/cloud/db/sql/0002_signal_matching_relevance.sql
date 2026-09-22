-- 0002_signal_matching_relevance
-- Additive PC-05 relevance persistence. 0001 remains immutable.

ALTER TABLE cloud_watchlist_version
    ADD COLUMN entities TEXT NOT NULL DEFAULT '[]';

ALTER TABLE cloud_watchlist_version
    ADD COLUMN domains TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS cloud_relevance_evaluation (
    evaluation_id        TEXT PRIMARY KEY,
    workspace_id         TEXT NOT NULL
                         REFERENCES cloud_workspace (workspace_id) ON DELETE CASCADE,
    watchlist_id         TEXT NOT NULL
                         REFERENCES cloud_watchlist (watchlist_id) ON DELETE CASCADE,
    watchlist_version_id TEXT NOT NULL
                         REFERENCES cloud_watchlist_version (version_id) ON DELETE CASCADE,
    signal_id            TEXT NOT NULL
                         REFERENCES cloud_signal (signal_id) ON DELETE CASCADE,
    signal_snapshot_id   TEXT NOT NULL
                         REFERENCES cloud_signal_evaluation (snapshot_id) ON DELETE CASCADE,
    radar_id             TEXT NOT NULL DEFAULT '',
    radar_run_id         TEXT NOT NULL DEFAULT '',
    decision             TEXT NOT NULL,
    relevance_score      DOUBLE PRECISION NOT NULL,
    relevance_band       TEXT NOT NULL,
    relevance_confidence TEXT NOT NULL,
    reasons_json         TEXT NOT NULL,
    components_json      TEXT NOT NULL,
    matcher_version      TEXT NOT NULL,
    evaluated_at         TEXT NOT NULL,
    UNIQUE (
        workspace_id,
        watchlist_version_id,
        signal_snapshot_id,
        matcher_version
    )
);

CREATE INDEX IF NOT EXISTS ix_relevance_eval_watchlist
    ON cloud_relevance_evaluation
       (workspace_id, watchlist_id, signal_id, evaluated_at);

CREATE TABLE IF NOT EXISTS cloud_watchlist_signal_match (
    match_id                TEXT PRIMARY KEY,
    workspace_id            TEXT NOT NULL REFERENCES cloud_workspace (workspace_id),
    watchlist_id            TEXT NOT NULL REFERENCES cloud_watchlist (watchlist_id),
    signal_id               TEXT NOT NULL REFERENCES cloud_signal (signal_id),
    status                  TEXT NOT NULL,
    current_relevance_score DOUBLE PRECISION NOT NULL,
    current_band            TEXT NOT NULL,
    current_confidence      TEXT NOT NULL,
    current_evaluation_id   TEXT NOT NULL
                            REFERENCES cloud_relevance_evaluation (evaluation_id),
    first_matched_at        TEXT NOT NULL,
    last_matched_at         TEXT NOT NULL,
    UNIQUE (workspace_id, watchlist_id, signal_id)
);

CREATE INDEX IF NOT EXISTS ix_watchlist_signal_match_scope
    ON cloud_watchlist_signal_match (workspace_id, watchlist_id, status);

CREATE TABLE IF NOT EXISTS cloud_relevance_evaluation_run (
    evaluation_id TEXT NOT NULL REFERENCES cloud_relevance_evaluation (evaluation_id),
    radar_run_id  TEXT NOT NULL REFERENCES cloud_radar_run (run_id) ON DELETE CASCADE,
    PRIMARY KEY (evaluation_id, radar_run_id)
);
