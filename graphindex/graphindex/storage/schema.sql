-- graphindex SQLite schema (graph + metadata + health)
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    path      TEXT PRIMARY KEY,
    language  TEXT,
    size      INTEGER,
    mtime     REAL,
    sha       TEXT,           -- content hash for incremental detection
    commit_id TEXT,
    indexed_at REAL
);

CREATE TABLE IF NOT EXISTS nodes (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    name       TEXT,
    path       TEXT,
    language   TEXT,
    start_line INTEGER,
    end_line   INTEGER,
    signature  TEXT,
    params     TEXT,          -- full parameter setup, e.g. "(a: int, b=2)"
    search_string TEXT,       -- canonical searchable text (embedding input)
    type_hint  TEXT,
    summary    TEXT,
    tags       TEXT,          -- json array
    state      TEXT,
    degree     INTEGER DEFAULT 0,
    flags      TEXT,          -- json array
    commit_id  TEXT,
    extra      TEXT           -- json object
);

CREATE INDEX IF NOT EXISTS idx_nodes_path ON nodes(path);
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_lang ON nodes(language);

CREATE TABLE IF NOT EXISTS edges (
    id       TEXT PRIMARY KEY,
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL,
    kind     TEXT NOT NULL,
    weight   REAL DEFAULT 1.0,
    resolved INTEGER DEFAULT 1,
    extra    TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);

-- Full-text index over symbol names + summaries for fast text/regex prefilter.
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
    id UNINDEXED, name, signature, params, summary, tags, search_string, code,
    tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS health (
    run_id     TEXT,
    ts         REAL,
    metric     TEXT,
    value      REAL
);
