-- Rosetta schema v2 · upstream 加 is_default 字段
-- protocol → upstream 1:N,但每个 protocol 至多一个 is_default=1(partial unique index)
-- selector 在 r-upstream header 缺失时,按入口 protocol 严格同 protocol 找 default

ALTER TABLE upstreams ADD COLUMN is_default INTEGER NOT NULL DEFAULT 0;

-- partial unique index:每个 protocol 最多一行 is_default=1。mock 的 protocol='any' 也走这条
-- 索引,但 mock 永远 is_default=0(`MOCK_UPSTREAM_FIELDS` 钉死),不会触发冲突
CREATE UNIQUE INDEX ux_upstreams_default_per_protocol
    ON upstreams(protocol) WHERE is_default = 1;

PRAGMA user_version = 2;
