"""`rosetta logs` — 最近请求流水。

v0.1 logs 表由 logger 组件写入,v0 未接入 → 常态空表,显示 "no logs yet"。
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from rosetta.cli.render import Renderer
from rosetta.sdk.client import ProxyClient


def logs_cmd(
    n: Annotated[int, typer.Option("-n", "--limit", help="最多显示多少条")] = 50,
    provider: Annotated[
        str | None, typer.Option("--provider", help="按 provider name 过滤")
    ] = None,
) -> None:
    """显示最近 N 条请求日志(时间降序)。"""
    asyncio.run(_run(n=n, provider=provider))


async def _run(*, n: int, provider: str | None) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            items = await client.list_logs(limit=n, provider=provider)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return

    if not items:
        Renderer.out("no logs yet")
        return
    Renderer.table(
        ["id", "created_at", "provider", "model", "in→out", "ms", "status"],
        [
            [
                entry.id,
                entry.created_at.isoformat(timespec="seconds"),
                entry.provider,
                entry.model,
                f"{entry.input_tokens or 0}→{entry.output_tokens or 0}",
                entry.latency_ms,
                entry.status,
            ]
            for entry in items
        ],
    )


def register(app: typer.Typer) -> None:
    app.command("logs", help="最近请求日志")(logs_cmd)
