-- Rosetta schema v6 · API 类型字典表
-- name 是语义值,path 是 HTTP 路径。server_api 和 upstream.native_api 都引用 name。
--
-- 开发期曾短暂使用 api_formats 表名。这里把兼容逻辑合并在 v6:
-- - 若 api_formats 存在,复制其数据到 api_types 后删除
-- - 若 api_formats 不存在,临时建空表保证复制语句可执行

CREATE TABLE IF NOT EXISTS api_formats (
    name       TEXT PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS api_types (
    name       TEXT PRIMARY KEY,
    path       TEXT NOT NULL UNIQUE,
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO api_types (name, path, enabled, created_at)
SELECT name, path, enabled, created_at FROM api_formats;

INSERT OR IGNORE INTO api_types (name, path, enabled) VALUES
    ('messages', '/v1/messages', 1),
    ('completions', '/v1/chat/completions', 1),
    ('responses', '/v1/responses', 1);

DROP TABLE IF EXISTS api_formats;

PRAGMA user_version = 6;
