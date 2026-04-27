-- Rosetta schema v4 · logs 加 client_addr / upstream_url 字段
-- 用于排查"谁在调 server / 这条 log 打到了哪个上游 endpoint":
--   client_addr  ← FastAPI request.client 的 "host:port" 字符串(本机 127.0.0.1 也记)
--   upstream_url ← 请求当时的 upstream.base_url 快照(mock 路径填 'mock://');
--                  快照而非外键,后续编辑 upstream.base_url 不影响历史 log
-- 老 log 两字段为 NULL,UI / CLI 显示 "-"。

ALTER TABLE logs ADD COLUMN client_addr TEXT;
ALTER TABLE logs ADD COLUMN upstream_url TEXT;

PRAGMA user_version = 4;
