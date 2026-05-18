-- OpenCOAT Runtime SQLite schema (v0.1).
-- Mirrors v0.2 §4.3.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS concerns (
    id                       TEXT PRIMARY KEY,
    kind                     TEXT NOT NULL CHECK (kind IN ('concern', 'meta_concern')),
    generated_type           TEXT,
    name                     TEXT NOT NULL,
    description              TEXT,
    source_json              TEXT,
    joinpoint_selectors_json TEXT,
    pointcut_json            TEXT,
    advice_json              TEXT,
    weaving_policy_json      TEXT,
    scope_json               TEXT,
    activation_state_json    TEXT,
    metrics_json             TEXT,
    lifecycle_state          TEXT NOT NULL DEFAULT 'created',
    schema_version           TEXT NOT NULL DEFAULT '0.1.0',
    created_at               TEXT,
    updated_at               TEXT
);
CREATE INDEX IF NOT EXISTS idx_concerns_kind            ON concerns(kind);
CREATE INDEX IF NOT EXISTS idx_concerns_generated_type  ON concerns(generated_type);
CREATE INDEX IF NOT EXISTS idx_concerns_lifecycle_state ON concerns(lifecycle_state);

CREATE TABLE IF NOT EXISTS concern_tags (
    concern_id TEXT NOT NULL REFERENCES concerns(id) ON DELETE CASCADE,
    tag        TEXT NOT NULL,
    PRIMARY KEY (concern_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_concern_tags_tag ON concern_tags(tag);

CREATE TABLE IF NOT EXISTS concern_relations (
    src_id        TEXT NOT NULL REFERENCES concerns(id) ON DELETE CASCADE,
    dst_id        TEXT NOT NULL REFERENCES concerns(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    weight        REAL NOT NULL DEFAULT 1.0,
    created_at    TEXT,
    PRIMARY KEY (src_id, dst_id, relation_type)
);

CREATE TABLE IF NOT EXISTS activation_log (
    concern_id  TEXT NOT NULL REFERENCES concerns(id) ON DELETE CASCADE,
    joinpoint_id TEXT NOT NULL,
    score       REAL NOT NULL,
    ts          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activation_log_concern ON activation_log(concern_id);
CREATE INDEX IF NOT EXISTS idx_activation_log_ts      ON activation_log(ts);

CREATE TABLE IF NOT EXISTS verification_log (
    concern_id     TEXT NOT NULL REFERENCES concerns(id) ON DELETE CASCADE,
    weave_id        TEXT NOT NULL,
    satisfied      INTEGER NOT NULL,
    evidence_json  TEXT,
    ts             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeat_log (
    ts             TEXT PRIMARY KEY,
    decay_count    INTEGER NOT NULL DEFAULT 0,
    merge_count    INTEGER NOT NULL DEFAULT 0,
    archive_count  INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS concern_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    concern_id  TEXT NOT NULL,
    actor       TEXT,
    reason      TEXT,
    diff_json   TEXT,
    ts          TEXT NOT NULL
);
