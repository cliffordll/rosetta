-- Rosetta schema v2 · 移除 routes 表
-- 2026-04 简化:pick_provider 改为强制 x-rosetta-provider header,不再做 model_glob 匹配
-- DROP ... IF EXISTS 对新 DB(001 已不创建 routes 表)也无害

DROP TABLE IF EXISTS routes;

PRAGMA user_version = 2;
