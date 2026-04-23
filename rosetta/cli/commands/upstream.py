"""`rosetta upstream` — upstream 的 add / list / remove。

update / test 留到 v1+(FEATURE 附录 B)。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, get_args

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.upstreams import UpstreamCreate, UpstreamProtocolCreatable
from rosetta.server.database.models import UpstreamProvider

_ALLOWED_PROTOCOLS = get_args(UpstreamProtocolCreatable)
_ALLOWED_PROVIDERS = get_args(UpstreamProvider)

app = typer.Typer(
    help="upstream 管理",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("list")
def list_cmd() -> None:
    """列出所有 upstream。"""
    asyncio.run(_list())


async def _list() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            items = await client.list_upstreams()
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return

    if not items:
        Renderer.out("no upstreams yet")
        return
    Renderer.table(
        ["id", "name", "protocol", "provider", "base_url", "enabled"],
        [
            [u.id, u.name, u.protocol, u.provider, u.base_url, u.enabled]
            for u in items
        ],
    )


@app.command("add")
def add_cmd(
    name: Annotated[str, typer.Option("--name", help="upstream 名")],
    base_url: Annotated[str, typer.Option("--base-url", help="上游根地址(必填)")],
    protocol: Annotated[
        str,
        typer.Option(
            "--protocol", help="messages | completions | responses(默认 messages)"
        ),
    ] = "messages",
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="上游 api key(可选)")
    ] = None,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="厂商:anthropic / openai / openrouter / google / ollama / vllm / custom",
        ),
    ] = "custom",
) -> None:
    """新增一个 upstream。"""
    if protocol not in _ALLOWED_PROTOCOLS:
        Renderer.die(f"--protocol 必须是 messages/completions/responses,收到 {protocol!r}")
        return
    if provider not in _ALLOWED_PROVIDERS:
        Renderer.die(
            f"--provider 必须是 {'/'.join(_ALLOWED_PROVIDERS)},收到 {provider!r}"
        )
        return
    payload = UpstreamCreate(
        name=name,
        protocol=protocol,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        api_key=api_key,
        base_url=base_url,
    )
    asyncio.run(_create(payload))


async def _create(payload: UpstreamCreate) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            created = await client.create_upstream(payload)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"创建失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(
        f"upstream '{created.name}' created "
        f"(id={created.id}, protocol={created.protocol}, enabled={created.enabled})"
    )


@app.command("remove")
def remove_cmd(upstream_id: Annotated[str, typer.Argument(help="要删除的 upstream id")]) -> None:
    """按 id 删 upstream。"""
    asyncio.run(_remove(upstream_id))


async def _remove(upstream_id: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            await client.delete_upstream(upstream_id)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"删除失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(f"upstream id={upstream_id} removed")


@app.command("mock")
def mock_cmd(
    force: Annotated[
        bool,
        typer.Option("--force", help="mock 已存在时先删除再重建(默认幂等跳过)"),
    ] = False,
) -> None:
    """恢复内置 mock upstream(误删 / 重置出厂配置用)。"""
    asyncio.run(_restore_mock(force))


async def _restore_mock(force: bool) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.restore_mock_upstream(force=force)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"恢复失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    verb = "restored" if result.created else "already exists"
    Renderer.out(f"mock upstream {verb} (id={result.upstream.id})")


def register(app_root: typer.Typer) -> None:
    app_root.add_typer(app, name="upstream")
