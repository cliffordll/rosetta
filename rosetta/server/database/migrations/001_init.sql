-- Rosetta schema v1 · 初始化
-- 和 rosetta/server/database/models.py 的 ORM 声明保持字段对齐
-- 执行时机:DB 文件首次创建 / PRAGMA user_version = 0 时由 session.init_db() 调用

CREATE TABLE providers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE,
    type       TEXT    NOT NULL,                  -- anthropic / openai / openrouter / custom
    base_url   TEXT,                              -- NULL 时按 type 取默认
    api_key    TEXT    NOT NULL,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provider_id   INTEGER REFERENCES providers(id),
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    latency_ms    INTEGER,
    status        TEXT    NOT NULL,               -- ok / error / timeout
    error         TEXT
);

CREATE INDEX idx_logs_created_at ON logs(created_at);

PRAGMA user_version = 1;
