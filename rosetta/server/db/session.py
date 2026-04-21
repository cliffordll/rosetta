"""SQLite + aiosqlite 异步 engine / session 工厂。

启动时 `init_db()` 负责:
  - 确保 `~/.rosetta/` 目录存在
  - 读 `PRAGMA user_version` 判断 schema 版本;为 0(新库 / 未初始化)时跑 migrations/001_init.sql
  - 创建 async engine 和 session maker

关闭时 `dispose_db()` 释放连接池。FastAPI lifespan 钩子里调。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEFAULT_DB_PATH = Path.home() / ".rosetta" / "rosetta.db"
CURRENT_SCHEMA_VERSION = 1


@dataclass
class _DBState:
    engine: AsyncEngine | None = None
    session_maker: async_sessionmaker[AsyncSession] | None = None


_state = _DBState()


def _db_url(db_path: Path) -> str:
    # as_posix 把 Windows 反斜杠转正斜杠,避免 URL 解析问题
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


async def _maybe_run_migrations(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute("PRAGMA user_version;") as cursor:
            row = await cursor.fetchone()
        current = int(row[0]) if row else 0

        if current > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"DB schema version {current} 比当前代码支持的 {CURRENT_SCHEMA_VERSION} 还新,"
                f"拒绝启动(可能是把老 server 指向新 DB)"
            )

        if current < CURRENT_SCHEMA_VERSION:
            sql_path = Path(__file__).parent / "migrations" / "001_init.sql"
            sql = sql_path.read_text(encoding="utf-8")
            await conn.executescript(sql)
            await conn.commit()


async def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    await _maybe_run_migrations(db_path)
    _state.engine = create_async_engine(_db_url(db_path))
    _state.session_maker = async_sessionmaker(_state.engine, expire_on_commit=False)


async def dispose_db() -> None:
    if _state.engine is not None:
        await _state.engine.dispose()
    _state.engine = None
    _state.session_maker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    if _state.session_maker is None:
        raise RuntimeError("DB 未初始化,先在 lifespan 里调 init_db()")
    async with _state.session_maker() as session:
        yield session


async def count_providers() -> int:
    """给 /admin/status 用的小工具:只数一下 providers 表行数。"""
    from sqlalchemy import func, select

    from rosetta.server.db.models import Provider

    if _state.session_maker is None:
        return 0
    async with _state.session_maker() as session:
        result = await session.execute(select(func.count()).select_from(Provider))
        return int(result.scalar_one())
