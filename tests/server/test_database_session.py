from __future__ import annotations

import asyncio
import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from rosetta.server.database.session import close_session_safely


class _CloseRaises:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def close(self) -> None:
        raise self.exc


class _CloseWaits:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        await asyncio.sleep(0)
        self.closed = True


def _operational_error(message: str) -> OperationalError:
    return OperationalError(
        statement=None,
        params=None,
        orig=sqlite3.OperationalError(message),
    )


async def test_close_session_safely_ignores_sqlite_no_active_connection() -> None:
    session = _CloseRaises(_operational_error("no active connection"))

    await close_session_safely(session)  # type: ignore[arg-type]


async def test_close_session_safely_does_not_raise_when_cancelled() -> None:
    session = _CloseWaits()

    task = asyncio.create_task(close_session_safely(session))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    task.cancel()
    await task

    # asyncio.shield 在取消时不保证 close 立即完成,但不应冒泡 CancelledError


async def test_close_session_safely_reraises_other_operational_errors() -> None:
    session = _CloseRaises(_operational_error("database is locked"))

    with pytest.raises(OperationalError, match="database is locked"):
        await close_session_safely(session)  # type: ignore[arg-type]
