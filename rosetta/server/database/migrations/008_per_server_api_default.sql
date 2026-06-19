-- Rosetta schema v8 · default upstream 支持 per-server_api + global 双层 fallback
--
-- settings 表结构不变,新增键格式:
--   - per-server_api: 'default_upstream_id:<server_api>'
--   - global:         'default_upstream_id'
-- selector 逻辑:先查 per-server_api,没有再查 global,都没有再 400。
-- v7 留下的 'default_upstream_id' 全局键继续生效,作为所有 server_api 的兜底。

PRAGMA user_version = 8;
