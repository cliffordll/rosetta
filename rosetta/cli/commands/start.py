"""`rosetta start` — 确保 server 在后台跑着。

与 `discover` 不同:spawn 的 server **不**绑定 CLI 进程为 parent,
让它在 CLI 退出后继续存活(真后台化)。这样后续 `rosetta status` / `provider`
等命令才能连到同一个 server。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time

import httpx
import psutil
import typer

from rosetta.cli.render import die, out
from rosetta.server.runtime.endpoint import Endpoint, delete_endpoint, read_endpoint
from rosetta.server.runtime.lockfile import acquire_spawn_lock, release_spawn_lock

_WAIT_TIMEOUT_SEC = 10.0
_POLL_INTERVAL_SEC = 0.1

_SPAWN_CMD = [sys.executable, "-m", "rosetta.server"]


def start_cmd() -> None:
    """后台启动 rosetta-server(若未跑),立即返回。"""
    asyncio.run(_run())


async def _run() -> None:
    # 已跑就直接报告
    ep = read_endpoint()
    if ep is not None and psutil.pid_exists(ep["pid"]) and await _ping(ep["url"]):
        out(f"already running at {ep['url']} (pid {ep['pid']})")
        return

    if ep is not None and not psutil.pid_exists(ep["pid"]):
        delete_endpoint()

    try:
        lock_fd = acquire_spawn_lock()
    except FileExistsError:
        die("另一个进程正在启动 server,请稍后再试")
        return  # for type checker

    try:
        _spawn_detached()
        ep = await _wait_ready()
        if ep is None:
            die(f"server {_WAIT_TIMEOUT_SEC}s 内未就绪")
            return
        out(f"server started on {ep['url']} (pid {ep['pid']})")
    finally:
        release_spawn_lock(lock_fd)


def _spawn_detached() -> None:
    """不传 --parent-pid,让 server 独立存活于 CLI 进程之外。"""
    if sys.platform == "win32":
        subprocess.Popen(
            _SPAWN_CMD,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0x00000008 | 0x00000200,  # DETACHED + NEW_PROCESS_GROUP
        )
    else:
        subprocess.Popen(
            _SPAWN_CMD,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )


async def _wait_ready() -> Endpoint | None:
    deadline = time.monotonic() + _WAIT_TIMEOUT_SEC
    while time.monotonic() < deadline:
        ep = read_endpoint()
        if ep is not None and psutil.pid_exists(ep["pid"]) and await _ping(ep["url"]):
            return ep
        await asyncio.sleep(_POLL_INTERVAL_SEC)
    return None


async def _ping(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{url}/admin/ping")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


def register(app: typer.Typer) -> None:
    app.command("start", help="后台启动 server(若未跑)")(start_cmd)
