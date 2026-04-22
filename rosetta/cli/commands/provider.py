"""`rosetta provider` — provider 的 add / list / remove。

update / test 留到 v1+(FEATURE 附录 B)。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, get_args

import httpx
import typer

from rosetta.cli.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.admin.providers import ProviderCreate, ProviderType

_ALLOWED_TYPES = get_args(ProviderType)

app = typer.Typer(
    help="provider 管理",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("list")
def list_cmd() -> None:
    """列出所有 provider。"""
    asyncio.run(_list())


async def _list() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            items = await client.list_providers()
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return

    if not items:
        Renderer.out("no providers yet")
        return
    Renderer.table(
        ["id", "name", "type", "base_url", "enabled"],
        [[p.id, p.name, p.type, p.base_url or "-", p.enabled] for p in items],
    )


@app.command("add")
def add_cmd(
    name: Annotated[str, typer.Option("--name", help="provider 名")],
    type: Annotated[str, typer.Option("--type", help="anthropic | openai | openrouter | custom")],
    api_key: Annotated[str, typer.Option("--api-key", help="上游 api key")],
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="上游根地址(留空按 type 取默认)")
    ] = None,
) -> None:
    """新增一个 provider。"""
    if type not in _ALLOWED_TYPES:
        Renderer.die(f"--type 必须是 anthropic/openai/openrouter/custom,收到 {type!r}")
        return
    payload = ProviderCreate(
        name=name,
        type=type,  # type: ignore[arg-type]
        api_key=api_key,
        base_url=base_url,
    )
    asyncio.run(_create(payload))


async def _create(payload: ProviderCreate) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            created = await client.create_provider(payload)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"创建失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(
        f"provider '{created.name}' created "
        f"(id={created.id}, type={created.type}, enabled={created.enabled})"
    )


@app.command("remove")
def remove_cmd(provider_id: Annotated[int, typer.Argument(help="要删除的 provider id")]) -> None:
    """按 id 删 provider;server 级联删引用它的 route。"""
    asyncio.run(_remove(provider_id))


async def _remove(provider_id: int) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            await client.delete_provider(provider_id)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"删除失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(f"provider id={provider_id} removed")


def register(app_root: typer.Typer) -> None:
    app_root.add_typer(app, name="provider")
