"""SDK discover / spawn 集成测试(FEATURE 4.1)。

两场景:
1. server 未跑 → `discover()` 自动 spawn,endpoint.json 出现,ping 通
2. server 已在跑 → 再 `discover()` 复用,pid 与首次一致,不新起进程

**集成测试**:真会启动 `python -m rosetta.server` 子进程,污染 `~/.rosetta/`。
默认跳过;用 `uv run pytest --integration` 触发。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from typing import Any, cast

import psutil
import pytest

from rosetta.sdk.discover import discover
from rosetta.server.runtime.endpoint import (
    ENDPOINT_PATH,
    delete_endpoint,
    read_endpoint,
)
from rosetta.server.runtime.lockfile import LOCK_PATH

_DISCOVER_DEADLINE_SEC = 20.0


def _kill_lingering_servers() -> None:
    """杀掉残留 rosetta-server 进程(基于 cmdline 匹配)。"""
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            info = cast(dict[str, Any], p.info)
            cmd = cast(list[Any], info.get("cmdline") or [])
            if any("rosetta.server" in str(c) for c in cmd):
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


@pytest.fixture
def clean_state() -> Iterator[None]:
    """测试前后清 endpoint.json / spawn.lock / 残留 server 进程。"""
    _kill_lingering_servers()
    delete_endpoint()
    with contextlib.suppress(FileNotFoundError):
        LOCK_PATH.unlink()
    yield
    _kill_lingering_servers()
    delete_endpoint()
    with contextlib.suppress(FileNotFoundError):
        LOCK_PATH.unlink()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_state")
async def test_discover_spawns_when_missing() -> None:
    assert read_endpoint() is None
    ep = await asyncio.wait_for(discover(), timeout=_DISCOVER_DEADLINE_SEC)
    assert ep["pid"] > 0
    assert psutil.pid_exists(ep["pid"])
    assert ENDPOINT_PATH.exists()


@pytest.mark.integration
@pytest.mark.usefixtures("clean_state")
async def test_discover_reuses_existing() -> None:
    first = await asyncio.wait_for(discover(), timeout=_DISCOVER_DEADLINE_SEC)
    second = await asyncio.wait_for(discover(), timeout=_DISCOVER_DEADLINE_SEC)
    assert first["pid"] == second["pid"], "复用路径应不新 spawn"
    assert first["url"] == second["url"]
