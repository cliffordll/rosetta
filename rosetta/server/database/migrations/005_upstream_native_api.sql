-- Rosetta schema v5 · upstream 字段 protocol 重命名为 native_api
-- v0.2 管理面用 native_api 表示上游原生 API 类型,server_api 表示 server 入口 API 格式。

DROP INDEX IF EXISTS ux_upstreams_default_per_protocol;
DROP INDEX IF EXISTS ux_upstreams_default_per_native_api;

ALTER TABLE upstreams RENAME COLUMN protocol TO native_api;

CREATE UNIQUE INDEX ux_upstreams_default_per_native_api
    ON upstreams(native_api) WHERE is_default = 1;

PRAGMA user_version = 5;
