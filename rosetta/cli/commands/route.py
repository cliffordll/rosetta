"""`rosetta route` — 路由规则的 list / add / remove / clear。

server 端 `PUT /admin/routes` 是批量替换;CLI 侧做语义适配:
- `add`:GET 当前 → 追加 → PUT
- `remove <id>`:GET 当前 → 过滤 → PUT
- `clear`:PUT []

CLI 是单进程执行,竞态只出现在多个 CLI 同时改,v0 不处理。
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.admin.routes import RouteIn, RouteOut

app = typer.Typer(
    help="路由规则管理",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("list")
def list_cmd() -> None:
    asyncio.run(_list())


async def _list() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            items = await client.list_routes()
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return

    if not items:
        Renderer.out("no routes yet")
        return
    Renderer.table(
        ["id", "pattern", "provider", "priority"],
        [[r.id, r.model_glob, r.provider, r.priority] for r in items],
    )


@app.command("add")
def add_cmd(
    pattern: Annotated[str, typer.Option("--pattern", help="model_glob,e.g. 'claude-*'")],
    provider: Annotated[str, typer.Option("--provider", help="provider name")],
    priority: Annotated[int, typer.Option("--priority", help="数字越小越优先")] = 0,
) -> None:
    """追加一条路由规则。"""
    asyncio.run(_add(pattern=pattern, provider=provider, priority=priority))


async def _add(*, pattern: str, provider: str, priority: int) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            current = await client.list_routes()
            new_list = [_to_in(r) for r in current]
            new_list.append(RouteIn(model_glob=pattern, provider=provider, priority=priority))
            await client.replace_routes(new_list)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"add 失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(f"route added: '{pattern}' → {provider} (priority={priority})")


@app.command("remove")
def remove_cmd(route_id: Annotated[int, typer.Argument(help="要删除的 route id")]) -> None:
    """按 id 删一条路由规则。"""
    asyncio.run(_remove(route_id))


async def _remove(route_id: int) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            current = await client.list_routes()
            target = next((r for r in current if r.id == route_id), None)
            if target is None:
                Renderer.die(f"route id={route_id} 不存在")
                return
            new_list = [_to_in(r) for r in current if r.id != route_id]
            await client.replace_routes(new_list)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"remove 失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(f"route id={route_id} removed")


@app.command("clear")
def clear_cmd() -> None:
    """删空所有路由规则。"""
    asyncio.run(_clear())


async def _clear() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            await client.replace_routes([])
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out("all routes cleared")


def _to_in(r: RouteOut) -> RouteIn:
    return RouteIn(model_glob=r.model_glob, provider=r.provider, priority=r.priority)


def register(app_root: typer.Typer) -> None:
    app_root.add_typer(app, name="route")
