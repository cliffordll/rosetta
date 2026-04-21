"""`~/.rosetta/spawn.lock` 独占抢锁,防止并发 spawn 双开。

- 抢锁:`os.open(O_CREAT | O_EXCL | O_WRONLY)`(Linux / Windows 通用)
- 陈旧检测:读锁内 PID,psutil 判进程已死 → 当陈旧锁删除重试
- 放锁:关 fd 并删文件(全幂等)
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import psutil

LOCK_PATH = Path.home() / ".rosetta" / "spawn.lock"


def acquire_spawn_lock() -> int:
    """抢锁;别人持有时 raise FileExistsError。返回可写入 PID 的 fd。"""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # 已存在 → 看是真有进程在持,还是陈旧锁
        if not _is_stale_lock():
            raise
        # 陈旧 → 清掉再抢一次
        _force_remove_lock()
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
    except OSError:
        os.close(fd)
        _force_remove_lock()
        raise
    return fd


def release_spawn_lock(fd: int | None) -> None:
    """关 fd + 删文件;全幂等(fd=None、已关、文件不存在都 OK)。"""
    if fd is not None:
        with contextlib.suppress(OSError):
            os.close(fd)
    _force_remove_lock()


def _is_stale_lock() -> bool:
    """读锁文件 PID;若进程已死或文件坏格式 → 算陈旧。"""
    try:
        raw = LOCK_PATH.read_text(encoding="utf-8").strip()
        old_pid = int(raw)
    except (OSError, ValueError):
        return True
    return not psutil.pid_exists(old_pid)


def _force_remove_lock() -> None:
    with contextlib.suppress(FileNotFoundError):
        LOCK_PATH.unlink()
