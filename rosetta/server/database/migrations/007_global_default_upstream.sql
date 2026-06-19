-- Rosetta schema v7 · default upstream 迁移到独立 settings 表
--
-- 用 key-value 表存全局配置,第一个键是 `default_upstream_id`。
-- 旧库的 `upstreams.is_default` 保留作只读冗余,新逻辑统一读 settings。

-- 1. 建 settings 表
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 2. 把旧的 per-protocol default 索引清掉(如果存在)
DROP INDEX IF EXISTS ux_upstreams_default_per_native_api;
DROP INDEX IF EXISTS ux_upstreams_default_per_protocol;
DROP INDEX IF EXISTS ux_upstreams_global_default;

-- 3. 迁移数据:旧库可能有多个 is_default=1 的行,保留 created_at 最新的一个
INSERT OR REPLACE INTO settings (key, value)
SELECT 'default_upstream_id', id
FROM upstreams
WHERE is_default = 1
ORDER BY created_at DESC, id DESC
LIMIT 1;

-- 4. 删除冗余列
ALTER TABLE upstreams DROP COLUMN is_default;

PRAGMA user_version = 7;
