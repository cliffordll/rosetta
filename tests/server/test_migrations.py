from __future__ import annotations

import sqlite3
from pathlib import Path


def test_v7_migrates_per_api_defaults_to_one_global_default(tmp_path: Path) -> None:
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
