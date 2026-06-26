-- Rosetta schema v10 - model tables
-- Create models and upstream_models tables, backfill from existing data.

CREATE TABLE IF NOT EXISTS models (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    alias       TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS upstream_models (
    upstream_id TEXT NOT NULL REFERENCES upstreams(id) ON DELETE CASCADE,
    model_id    TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    is_default  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (upstream_id, model_id)
);

CREATE INDEX IF NOT EXISTS idx_upstream_models_model ON upstream_models(model_id);

-- Backfill models from existing upstreams.model values (deduplicated)
INSERT OR IGNORE INTO models (id, name)
SELECT hex(randomblob(16)), upstreams.model
FROM upstreams
WHERE upstreams.model IS NOT NULL AND upstreams.model != '';

-- Link every upstream to its model in upstream_models
INSERT OR IGNORE INTO upstream_models (upstream_id, model_id)
SELECT u.id, m.id
FROM upstreams u
JOIN models m ON m.name = u.model;

PRAGMA user_version = 10;
