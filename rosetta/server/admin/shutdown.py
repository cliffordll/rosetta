"""/admin/shutdown:触发 server 自身优雅关闭(阶段 4.2)。

行为
----
- 调用方立刻收到 `{"ok": true}` 响应
- server 在后台发起 `server.should_exit = True`,由 uvicorn 进入 graceful shutdown
  (停 accept → 等进行中请求 → 关连接 → lifespan 清理)
- 阶段 1.4 的 `__main__.py` 已配 `timeout_graceful_shutdown=30`,上限 30s

CLI `rosetta stop` 优先调这里;进程仍活着兜底用 psutil.kill(pid) 再补一刀。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


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
