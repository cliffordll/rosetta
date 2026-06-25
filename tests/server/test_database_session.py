from __future__ import annotations

import asyncio
import contextvars
import sqlite3

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from rosetta.server.database.session import _state, close_session_safely, dispose_db, init_db

_cancel_scope_marker: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "cancel_scope_marker",
    default=None,
)


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


class _CloseWaitsThenRaises:
    async def close(self) -> None:
        await asyncio.sleep(0)
        raise _operational_error("no active connection")


class _CloseCapturesContext:
    def __init__(self, values: list[str | None]) -> None:
        self.values = values

    async def close(self) -> None:
        self.values.append(_cancel_scope_marker.get())


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


async def test_close_session_safely_consumes_background_close_errors_when_cancelled() -> None:
    captured: list[object] = []
    event_loop = asyncio.get_running_loop()

    def _capture_exception(_loop: asyncio.AbstractEventLoop, context: dict[str, object]) -> None:
        captured.append(context.get("exception") or context.get("message"))

    event_loop.set_exception_handler(_capture_exception)
    session = _CloseWaitsThenRaises()

    task = asyncio.create_task(close_session_safely(session))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    task.cancel()
    await task
    await asyncio.sleep(0)

    assert captured == []


async def test_close_session_safely_runs_cleanup_in_fresh_context() -> None:
    values: list[str | None] = []
    token = _cancel_scope_marker.set("request-cancel-scope")
    try:
        await close_session_safely(_CloseCapturesContext(values))  # type: ignore[arg-type]
    finally:
        _cancel_scope_marker.reset(token)

    assert values == [None]


async def test_close_session_safely_reraises_other_operational_errors() -> None:
    session = _CloseRaises(_operational_error("database is locked"))

    with pytest.raises(OperationalError, match="database is locked"):
        await close_session_safely(session)  # type: ignore[arg-type]


async def test_init_db_uses_null_pool(tmp_path) -> None:
    await init_db(tmp_path / "rosetta.db")
    try:
        assert _state.engine is not None
        assert isinstance(_state.engine.sync_engine.pool, NullPool)
    finally:
        await dispose_db()


async def test_init_db_does_not_create_api_types_table(tmp_path) -> None:
    db_path = tmp_path / "rosetta.db"
    await init_db(db_path)
    try:
        with sqlite3.connect(db_path) as db:
            row = db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'api_types'"
            ).fetchone()
    finally:
        await dispose_db()

    assert row is None
