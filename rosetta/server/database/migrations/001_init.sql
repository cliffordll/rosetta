-- Rosetta schema v1 · 初始化
-- 和 rosetta/server/database/models.py 的 ORM 声明保持字段对齐
-- 执行时机:DB 文件首次创建 / PRAGMA user_version = 0 时由 session.init_db() 调用
--
-- `id` 类型:32 字符 UUID4 hex(Python `uuid.uuid4().hex`),由 ORM 在插入时填入。
-- 不用 INTEGER AUTOINCREMENT:字符串 id 分布式安全、外部引用更稳、日志里一眼能认出。

CREATE TABLE upstreams (
    id         TEXT    PRIMARY KEY,                       -- 32 字符 UUID4 hex
    name       TEXT    NOT NULL UNIQUE,
    protocol   TEXT    NOT NULL,                          -- messages / completions / responses / any(any 仅 mock 占位)
    provider   TEXT    NOT NULL DEFAULT 'custom',         -- anthropic / openai / openrouter / google / ollama / vllm / custom / mock
    base_url   TEXT    NOT NULL,                          -- 上游根地址,必填
    api_key    TEXT,                                      -- 可选,没填时客户端必须自带 x-api-key 透传
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE logs (
    id            TEXT    PRIMARY KEY,                    -- 32 字符 UUID4 hex
    upstream_id   TEXT    REFERENCES upstreams(id),
    model         TEXT,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    latency_ms    INTEGER,
    status        TEXT    NOT NULL,                       -- ok / error / timeout
    error         TEXT,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_logs_created_at ON logs(created_at);

-- seed:内置 mock upstream,forwarder 识别 provider='mock' 后短路掉 HTTP,
-- 本地 echo 生成响应。base_url 仅占位(短路不会真连),api_key 可空。
INSERT INTO upstreams (id, name, protocol, provider, base_url, api_key, enabled)
VALUES ('00000000000000000000000000000000', 'mock', 'any', 'mock', 'mock://', NULL, 1);

PRAGMA user_version = 1;
