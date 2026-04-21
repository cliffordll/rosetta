"""SDK 侧发现/启动 rosetta-server(DESIGN §6)。

流程
----
1. 读 `~/.rosetta/endpoint.json`
   - 不存在 → 进入 spawn 分支
   - 存在但 PID 已死 → 删掉 endpoint.json,进入 spawn 分支
   - 存在且 PID 活 → 直接复用(ping 失败才当作死)
2. spawn:先抢 `spawn.lock`
   - 抢到 → 自己 `python -m rosetta.server --parent-pid <caller>` detach 启动,
     然后轮询 endpoint.json + /admin/ping 直到就绪或超时
   - 抢不到 → 说明别人在 spawn,转为只轮询 endpoint.json + ping(最多 5s)
3. 返回可用的 `Endpoint`

与 server 侧 `runtime/lockfile.py` / `runtime/endpoint.py` 的实现对称:
同一把 spawn.lock,同一个 endpoint.json 格式,同一个原子写入语义。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time

import httpx
import psutil

from rosetta.server.runtime.endpoint import Endpoint, delete_endpoint, read_endpoint
from rosetta.server.runtime.lockfile import acquire_spawn_lock, release_spawn_lock

# 轮询 endpoint.json + /admin/ping 的总超时与间隔
_SPAWN_WAIT_TIMEOUT_SEC = 10.0
_POLL_INTERVAL_SEC = 0.1

# 新进程的命令行:与 FEATURE 4.1 动手清单一致,用 `python -m rosetta.server`
# 不依赖 exe(阶段 6 才打包)。
_SPAWN_CMD = [sys.executable, "-m", "rosetta.server"]


async def discover(
    *,
    parent_pid: int | None = None,
    spawn_if_missing: bool = True,
) -> Endpoint:
    """返回一个 **已 ping 通**(可用)的 Endpoint。

    - `parent_pid`:spawn 时传给 server 的 `--parent-pid`;None → 当前进程
    - `spawn_if_missing`:False 时,若 endpoint 不存在 / 不可达直接 raise
      `RuntimeError`,不启动新 server;SDK `.direct()` 分支 / 测试用
    """
    # 1. 先尝试已有 endpoint.json
    ep = await _check_existing_endpoint()
    if ep is not None:
        return ep

    if not spawn_if_missing:
        raise RuntimeError("no running rosetta-server (endpoint.json 不存在或不可达)")

    # 2. spawn:抢锁分支
    effective_parent = parent_pid if parent_pid is not None else os.getpid()

    spawned_ourselves = False
    lock_fd: int | None = None
    try:
        try:
            lock_fd = acquire_spawn_lock()
            spawned_ourselves = True
        except FileExistsError:
            lock_fd = None  # 别人在 spawn,走"只轮询"分支

        if spawned_ourselves:
            _spawn_server_detached(parent_pid=effective_parent)

        # 3. 轮询直到 endpoint.json 出现且 ping 通,或超时
        ep = await _wait_until_ready(deadline=time.monotonic() + _SPAWN_WAIT_TIMEOUT_SEC)
        if ep is None:
            raise RuntimeError(
                f"rosetta-server {_SPAWN_WAIT_TIMEOUT_SEC}s 内未就绪"
                f"({'自 spawn' if spawned_ourselves else '等待别人 spawn'})"
            )
        return ep
    finally:
        # 仅当自己抢到锁才 release(server 启动成功后自己会释放,但客户端手持
        # 兜底 release 以防 server 启动失败卡住锁)
        if spawned_ourselves:
            release_spawn_lock(lock_fd)


async def _check_existing_endpoint() -> Endpoint | None:
    """读 endpoint.json + PID 活性 + /admin/ping;任一失败返回 None 并清陈旧文件。"""
    ep = read_endpoint()
    if ep is None:
        return None
    if not psutil.pid_exists(ep["pid"]):
        delete_endpoint()
        return None
    if not await _ping(ep["url"]):
        return None
    return ep


async def _wait_until_ready(*, deadline: float) -> Endpoint | None:
    """轮询直到 endpoint.json 出现 + ping 通;超时返回 None。"""
    while time.monotonic() < deadline:
        ep = read_endpoint()
        if ep is not None and psutil.pid_exists(ep["pid"]) and await _ping(ep["url"]):
            return ep
        await asyncio.sleep(_POLL_INTERVAL_SEC)
    return None


async def _ping(url: str) -> bool:
    """短超时 ping /admin/ping;失败(含连接失败)返回 False。"""
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{url}/admin/ping")
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _spawn_server_detached(*, parent_pid: int) -> None:
    """后台启动 server,与当前进程 detach(关 stdio,不做 wait)。

    - Windows:`creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`
    - POSIX:`start_new_session=True`(脱离 caller 控制终端)
    """
    cmd = [*_SPAWN_CMD, "--parent-pid", str(parent_pid)]
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008;CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=0x00000008 | 0x00000200,
        )
    else:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
