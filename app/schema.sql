-- Nestify V2 — Clean DevSecOps Pipeline Schema

CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    input_type      TEXT NOT NULL CHECK(input_type IN ('zip', 'github', 'text', 'natural_language')),
    status          TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'scanning', 'fixing', 'rescanning', 'deploying', 'completed', 'live', 'failed')),
    source_payload  TEXT,
    stack_info      TEXT,
    security_report TEXT,
    security_score  INTEGER DEFAULT 0,
    fix_report      TEXT,
    deployment      TEXT,
    agentic_insights TEXT,
    learning_opt_out INTEGER DEFAULT 0,
    public_url      TEXT,
    preferred_provider TEXT,
    pipeline_state  TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    severity    TEXT NOT NULL CHECK(severity IN ('critical', 'high', 'medium', 'info')),
    type        TEXT NOT NULL,
    file        TEXT,
    line        INTEGER,
    description TEXT NOT NULL,
    recommendation TEXT,
    source      TEXT DEFAULT 'pattern_scan',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS fix_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    file        TEXT NOT NULL,
    fix_type    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK(status IN ('applied', 'manual_review', 'failed', 'simulation_failed')),
    note        TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS deployments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    provider        TEXT NOT NULL,
    deployment_url  TEXT,
    status          TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'deploying', 'success', 'failed')),
    details         TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL,
    stage       TEXT NOT NULL,
    level       TEXT DEFAULT 'info' CHECK(level IN ('info', 'warn', 'error', 'debug')),
    message     TEXT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS token_usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    model         TEXT NOT NULL,
    tokens_used   INTEGER DEFAULT 0,
    requests_made INTEGER DEFAULT 0,
    UNIQUE(date, model)
);

CREATE TABLE IF NOT EXISTS deployment_patterns (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER,
    pattern_id        TEXT NOT NULL UNIQUE,
    pattern_payload   TEXT NOT NULL,
    outcome           TEXT,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS deployment_outcomes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL,
    framework         TEXT,
    platform          TEXT,
    success           INTEGER NOT NULL DEFAULT 0,
    duration_seconds  INTEGER,
    cost_per_month    REAL,
    fixes_applied     TEXT,
    debate_transcript TEXT,
    learnings         TEXT,
    agentic_enabled   INTEGER DEFAULT 1,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
