"""admin 运维控制:/admin/ping、/admin/status、/admin/shutdown。

三者都是"对 server 进程自身的控制/探测",没有业务语义,合在一个文件便于维护。

- `/admin/ping`:最轻量健康检查(不进 DB)
- `/admin/status`:版本 + 启动时长 + providers 数量(用于 CLI `rosetta status`)
- `/admin/shutdown`:触发 uvicorn graceful shutdown
  - 响应先发,后台任务再置 `server.should_exit = True`
  - 阶段 1.4 的 `__main__.py` 已配 `timeout_graceful_shutdown=30`,上限 30s
  - CLI `rosetta stop` 优先调这里;兜底用 psutil.kill(pid)
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from rosetta import __version__
from rosetta.server.database.session import count_upstreams

router = APIRouter()

_START_MONO = time.monotonic()


# ---------- /admin/ping ----------


class PingResponse(BaseModel):
    ok: bool


@router.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    return PingResponse(ok=True)


# ---------- /admin/status ----------


class StatusResponse(BaseModel):
    version: str
    uptime_ms: int
    upstreams_count: int


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    uptime_ms = int((time.monotonic() - _START_MONO) * 1000)
    upstreams_count = await count_upstreams()
    return StatusResponse(
        version=__version__,
        uptime_ms=uptime_ms,
        upstreams_count=upstreams_count,
    )


# ---------- /admin/shutdown ----------


class ShutdownResponse(BaseModel):
    ok: bool


@router.post("/shutdown", response_model=ShutdownResponse)
async def shutdown(request: Request) -> ShutdownResponse:
    """触发 uvicorn 的优雅关闭流程;**响应先发,后关**。"""
    server = getattr(request.app.state, "uvicorn_server", None)

    async def _trigger() -> None:
        # 让当前响应先回到客户端,再 yield 给 uvicorn 去设置 should_exit
        await asyncio.sleep(0.05)
        if server is not None:
            server.should_exit = True

    # 后台触发,不阻塞响应
    asyncio.create_task(_trigger())  # noqa: RUF006 — 即发即忘,关闭不需等待
    return ShutdownResponse(ok=True)
