-- Rosetta schema v3 · upstream 加 model 字段(默认模型)
-- 客户端 body 不传 model(或为空字符串)时,forwarder 用 upstream.model 兜底;
-- upstream.model 现在要求配置;旧库 NULL 会在后续迁移中回填。
-- mock 行使用 mock-default 占位。

ALTER TABLE upstreams ADD COLUMN model TEXT;
UPDATE upstreams SET model = 'mock-default' WHERE name = 'mock' AND model IS NULL;

PRAGMA user_version = 3;
