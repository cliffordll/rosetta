from __future__ import annotations

import sqlite3
from pathlib import Path


def test_v7_migrates_per_api_defaults_to_global_default(tmp_path: Path) -> None:
    """007 把旧 per-native_api default 收敛成单个 global default key。"""
    db_path = tmp_path / "v6.db"
    migration_path = (
        Path(__file__).parents[2]
        / "rosetta"
        / "server"
        / "database"
        / "migrations"
        / "007_global_default_upstream.sql"
    )

    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE upstreams (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                native_api TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX ux_upstreams_default_per_native_api
                ON upstreams(native_api) WHERE is_default = 1;
            INSERT INTO upstreams VALUES
                ('older', 'older', 'messages', 1, '2026-01-01T00:00:00'),
                ('newer', 'newer', 'completions', 1, '2026-02-01T00:00:00');
            PRAGMA user_version = 6;
            """
        )
        db.executescript(migration_path.read_text(encoding="utf-8"))

        default_value = db.execute(
            "SELECT value FROM settings WHERE key = 'default_upstream_id'"
        ).fetchone()
        indexes = db.execute("PRAGMA index_list('upstreams')").fetchall()
        version = db.execute("PRAGMA user_version").fetchone()

    assert default_value == ("newer",)
    assert all(row[1] != "ux_upstreams_default_per_native_api" for row in indexes)
    assert version == (7,)


def test_v8_keeps_global_default_for_hybrid(tmp_path: Path) -> None:
    """008 保留 global default key,为 per-server_api + global hybrid 做准备。"""
    db_path = tmp_path / "v7.db"
    migration_008 = (
        Path(__file__).parents[2]
        / "rosetta"
        / "server"
        / "database"
        / "migrations"
        / "008_per_server_api_default.sql"
    )

    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE upstreams (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                native_api TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO settings VALUES ('default_upstream_id', 'only-global');
            PRAGMA user_version = 7;
            """
        )
        db.executescript(migration_008.read_text(encoding="utf-8"))

        global_value = db.execute(
            "SELECT value FROM settings WHERE key = 'default_upstream_id'"
        ).fetchone()
        version = db.execute("PRAGMA user_version").fetchone()

    assert global_value == ("only-global",)
    assert version == (8,)


def test_v9_adds_log_content_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "v8.db"
    migration_009 = (
        Path(__file__).parents[2]
        / "rosetta"
        / "server"
        / "database"
        / "migrations"
        / "009_logs_content.sql"
    )

    with sqlite3.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE logs (
                id TEXT PRIMARY KEY,
                upstream_id TEXT,
                model TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                latency_ms INTEGER,
                status TEXT NOT NULL,
                error TEXT,
                client_addr TEXT,
                upstream_url TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version = 8;
            """
        )
        db.executescript(migration_009.read_text(encoding="utf-8"))

        cols = db.execute("PRAGMA table_info('logs')").fetchall()
        version = db.execute("PRAGMA user_version").fetchone()

    col_names = [row[1] for row in cols]
    assert "request_text" in col_names
    assert "response_text" in col_names
    assert version == (9,)
