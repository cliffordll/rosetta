"""`rosetta guide` 命令:显示客户端配置说明文档。"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient


def register(app_root: typer.Typer) -> None:
    """将 guide 命令注册到 rosetta 主 Typer。"""

    @app_root.command(name="guide", help="显示客户端配置说明(codex / claude / opencode / readme)")
    def guide_cmd(  # pyright: ignore[reportUnusedFunction] — typer registers this nested command
        client: Annotated[str, typer.Argument(help="配置说明: codex | claude | opencode | readme")],
    ) -> None:
        """通过后端 API 显示客户端配置说明文档。"""
        asyncio.run(_guide(client.lower()))


async def _guide(client: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client_api:
            result = await client_api.get_client_guide(client)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    except Exception as e:
        Renderer.die(str(e))
        return
    print(f"\n=== Client: {client} ===\n")
    Renderer.out(result.content)
