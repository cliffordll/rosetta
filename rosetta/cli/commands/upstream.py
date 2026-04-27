"""`rosetta upstream` — upstream 的 add / list / update / remove / set-default / restore-mock。

`test` 留到 v1+(FEATURE 附录 B)。
"""

from __future__ import annotations

import asyncio
from typing import Annotated, get_args

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.upstreams import (
    UpstreamCreate,
    UpstreamProtocolCreatable,
    UpstreamUpdate,
)
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
        ["id", "name", "protocol", "provider", "model", "base_url", "enabled", "default"],
        [
            [
                u.id,
                u.name,
                u.protocol,
                u.provider,
                u.model or "-",
                u.base_url,
                u.enabled,
                u.is_default,
            ]
            for u in items
        ],
    )


@app.command("add")
def add_cmd(
    name: Annotated[str, typer.Option("--name", help="upstream 名")],
    base_url: Annotated[str, typer.Option("--base-url", help="上游根地址(必填)")],
    protocol: Annotated[
        str,
        typer.Option("--protocol", help="messages | completions | responses(默认 messages)"),
    ] = "messages",
    api_key: Annotated[str | None, typer.Option("--api-key", help="上游 api key(可选)")] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="该 upstream 的默认模型(可选);body 不传 model 时 server fallback 到这个",
        ),
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
        Renderer.die(f"--provider 必须是 {'/'.join(_ALLOWED_PROVIDERS)},收到 {provider!r}")
        return
    payload = UpstreamCreate(
        name=name,
        protocol=protocol,  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
        api_key=api_key,
        model=model,
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


@app.command("update")
def update_cmd(
    upstream_id: Annotated[str, typer.Argument(help="要更新的 upstream id")],
    name: Annotated[str | None, typer.Option("--name", help="新 name")] = None,
    base_url: Annotated[str | None, typer.Option("--base-url", help="新 base_url")] = None,
    protocol: Annotated[
        str | None,
        typer.Option("--protocol", help="新 protocol(改了且原行是 default 会自动清 default)"),
    ] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="新 provider")] = None,
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="新 api key(传值更新,留空不动)")
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", help="新 default model(传值更新,留空不动)"),
    ] = None,
    enabled: Annotated[
        bool | None, typer.Option("--enabled/--disabled", help="启用 / 禁用 upstream")
    ] = None,
) -> None:
    """部分更新 upstream;只改传入的字段。要清空 api_key / model 请走 GUI。"""
    if protocol is not None and protocol not in _ALLOWED_PROTOCOLS:
        Renderer.die(f"--protocol 必须是 messages/completions/responses,收到 {protocol!r}")
        return
    if provider is not None and provider not in _ALLOWED_PROVIDERS:
        Renderer.die(f"--provider 必须是 {'/'.join(_ALLOWED_PROVIDERS)},收到 {provider!r}")
        return

    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if base_url is not None:
        fields["base_url"] = base_url
    if protocol is not None:
        fields["protocol"] = protocol
    if provider is not None:
        fields["provider"] = provider
    if api_key is not None:
        fields["api_key"] = api_key
    if model is not None:
        fields["model"] = model
    if enabled is not None:
        fields["enabled"] = enabled
    if not fields:
        Renderer.die("update 至少要传一个字段;`-h` 看可选项")
        return

    payload = UpstreamUpdate.model_validate(fields)
    asyncio.run(_update(upstream_id, payload))


async def _update(upstream_id: str, payload: UpstreamUpdate) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            updated = await client.update_upstream(upstream_id, payload)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"更新失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(
        f"upstream '{updated.name}' updated "
        f"(id={updated.id}, protocol={updated.protocol}, model={updated.model or '-'})"
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


@app.command("set-default")
def set_default_cmd(
    name: Annotated[str, typer.Argument(help="要设为该协议默认的 upstream name")],
) -> None:
    """把 upstream 设为其 protocol 的默认上游(`x-rosetta-upstream` header 缺失时回退用)。"""
    asyncio.run(_set_default(name))


async def _set_default(name: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            updated = await client.set_default_upstream(name)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"设默认失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(f"upstream '{updated.name}' is now default for protocol={updated.protocol}")


@app.command("restore-mock")
def restore_mock_cmd(
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
