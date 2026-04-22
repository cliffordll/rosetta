"""`rosetta status` — server 状态 + provider / route 计数。"""

from __future__ import annotations

import asyncio

import typer

from rosetta.cli.render import Renderer
from rosetta.sdk.client import ProxyClient


def status_cmd() -> None:
    """显示 server 状态(running / not running)+ provider / route 计数。"""
    asyncio.run(_run())


async def _run() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            st = await client.status()
            providers = await client.list_providers()
            routes = await client.list_routes()
            Renderer.kv(
                {
                    "server": client.base_url,
                    "version": st.version,
                    "uptime_ms": st.uptime_ms,
                    "providers": f"{st.providers_count} ({len(providers)} via list)",
                    "routes": len(routes),
                }
            )
    except RuntimeError:
        Renderer.out("not running")


def register(app: typer.Typer) -> None:
    app.command("status", help="显示 server 状态")(status_cmd)
