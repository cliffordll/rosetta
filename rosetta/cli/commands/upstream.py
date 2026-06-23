"""`rosetta upstream` 命令集。

覆盖 add / list / update / remove / default / defaults / test / restore。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, get_args

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.upstreams import (
    UpstreamCreate,
    UpstreamNativeApiCreatable,
    UpstreamUpdate,
)
from rosetta.server.database.models import UpstreamProvider
from rosetta.shared.server_api import DEFAULT_SERVER_API_PATHS

_ALLOWED_NATIVE_APIS = get_args(UpstreamNativeApiCreatable)
_ALLOWED_PROVIDERS = get_args(UpstreamProvider)
_PROVIDER_GUIDES = {"codex": "codex.md", "claude": "claude.md", "readme": "readme.md"}
_NATIVE_API_ERR = "--native-api 必须是 messages/completions/responses"

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
        ["id", "name", "native_api", "provider", "model", "base_url", "enabled", "test"],
        [
            [
                u.id,
                u.name,
                _api_label(u.native_api),
                u.provider,
                u.model or "-",
                u.base_url,
                u.enabled,
                u.test_result or "-",
            ]
            for u in items
        ],
        no_wrap_columns={"id", "name", "provider", "enabled", "test"},
        max_widths={"base_url": 52, "model": 32},
    )


@app.command("add")
def add_cmd(
    name: Annotated[str, typer.Option("--name", help="upstream 名")],
    base_url: Annotated[str, typer.Option("--base-url", help="上游根地址(必填)")],
    native_api: Annotated[
        str,
        typer.Option(
            "--native-api",
            help=(
                "upstream native API: messages(/v1/messages) | "
                "completions(/v1/chat/completions) | responses(/v1/responses)"
            ),
        ),
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
    if native_api not in _ALLOWED_NATIVE_APIS:
        Renderer.die(f"{_NATIVE_API_ERR},收到 {native_api!r}")
        return
    if provider not in _ALLOWED_PROVIDERS:
        Renderer.die(f"--provider 必须是 {'/'.join(_ALLOWED_PROVIDERS)},收到 {provider!r}")
        return
    payload = UpstreamCreate(
        name=name,
        native_api=native_api,  # type: ignore[arg-type]
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
        f"(id={created.id}, native_api={created.native_api}, enabled={created.enabled})"
    )


@app.command("update")
def update_cmd(
    upstream_id: Annotated[str, typer.Argument(help="要更新的 upstream id")],
    name: Annotated[str | None, typer.Option("--name", help="新 name")] = None,
    base_url: Annotated[str | None, typer.Option("--base-url", help="新 base_url")] = None,
    native_api: Annotated[
        str | None,
        typer.Option(
            "--native-api",
            help=(
                "新 upstream native API: messages(/v1/messages) | "
                "completions(/v1/chat/completions) | responses(/v1/responses)"
            ),
        ),
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
    if native_api is not None and native_api not in _ALLOWED_NATIVE_APIS:
        Renderer.die(f"{_NATIVE_API_ERR},收到 {native_api!r}")
        return
    if provider is not None and provider not in _ALLOWED_PROVIDERS:
        Renderer.die(f"--provider 必须是 {'/'.join(_ALLOWED_PROVIDERS)},收到 {provider!r}")
        return

    fields: dict[str, object] = {}
    if name is not None:
        fields["name"] = name
    if base_url is not None:
        fields["base_url"] = base_url
    if native_api is not None:
        fields["native_api"] = native_api
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
        f"(id={updated.id}, native_api={updated.native_api}, model={updated.model or '-'})"
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


@app.command("default")
def default_cmd(
    name: Annotated[str, typer.Argument(help="要设为 model 默认的 upstream name")],
    model: Annotated[str, typer.Option("--model", help="模型名称")],
) -> None:
    """把 upstream 设为某个 model 的默认路由。"""
    asyncio.run(_model_default(name, model))


async def _model_default(name: str, model: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            updated = await client.set_model_default_upstream(name, model=model)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"设置 model 默认失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    Renderer.out(f"upstream '{updated.name}' is now default for model '{model}'")


@app.command("defaults")
def defaults_cmd() -> None:
    """查看 model 默认路由映射。"""
    asyncio.run(_model_defaults())


async def _model_defaults() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            defaults = await client.list_model_defaults()
    except httpx.HTTPStatusError as e:
        Renderer.die(f"读取 model 默认映射失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    if not defaults:
        Renderer.out("(empty)")
        return
    Renderer.table(["model", "upstream"], [[model, name] for model, name in defaults.items()])


@app.command("test")
def test_cmd(upstream_id: Annotated[str, typer.Argument(help="要测试的 upstream id")]) -> None:
    """按 upstream 自己的 native_api 发最小探测请求。"""
    asyncio.run(_test(upstream_id))


async def _test(upstream_id: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.test_upstream(upstream_id)
    except httpx.HTTPStatusError as e:
        Renderer.die(f"测试失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return

    head = (
        f"{'OK' if result.ok else 'FAIL'} "
        f"upstream={result.upstream_name} native_api={_api_label(result.native_api)} "
        f"category={result.category}"
    )
    if result.status_code is not None:
        head += f" status={result.status_code}"

    if result.ok:
        Renderer.out(f"{head} {result.summary}")
        return

    Renderer.err(head)
    Renderer.die(result.detail or result.summary)


@app.command("restore")
def restore_mock_cmd(
    force: Annotated[
        bool,
        typer.Option("--force", help="mock 已存在时先删除再重建(默认幂等跳过)"),
    ] = False,
) -> None:
    """恢复内置 mock upstream(误删 / 重置出厂配置用)。调用 `POST /admin/upstreams/restore-mock`。"""
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


@app.command("guide")
def guide_cmd(
    provider: Annotated[
        str,
        typer.Argument(help="配置说明: codex | claude | readme"),
    ],
) -> None:
    """显示客户端配置说明文档路径。"""
    filename = _PROVIDER_GUIDES.get(provider.lower())
    if filename is None:
        Renderer.die("--provider 必须是 codex/claude/readme")
        return
    Renderer.out(str(_repo_root() / "docs" / "providers" / filename))


def register(app_root: typer.Typer) -> None:
    app_root.add_typer(app, name="upstream")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _api_label(value: str) -> str:
    path = DEFAULT_SERVER_API_PATHS.get(value)
    return f"{value} ({path})" if path else value
