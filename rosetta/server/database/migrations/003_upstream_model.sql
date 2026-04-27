-- Rosetta schema v3 · upstream 加 model 字段(默认模型)
-- 客户端 body 不传 model(或为空字符串)时,forwarder 用 upstream.model 兜底;
-- upstream.model 也为 NULL 时维持原 body(让上游自己 4xx)。
-- mock 行钉死 NULL(mock.respond 自己解析 body.model;upstream.model 不参与 mock 路径)。

ALTER TABLE upstreams ADD COLUMN model TEXT;

PRAGMA user_version = 3;
