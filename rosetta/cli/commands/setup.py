"""`rosetta setup` commands: preview and apply local client config files."""

from __future__ import annotations

import asyncio
from typing import Annotated, cast

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.setup import SetupConfigOut, SetupTarget

_ALLOWED_TARGETS = {"codex", "claude", "opencode"}

app = typer.Typer(
    help="客户端本机配置预览和写入",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("preview")
def preview_cmd(
    target: Annotated[str, typer.Argument(help="客户端: codex | claude | opencode")],
    upstream_id: Annotated[str, typer.Option("--upstream-id", help="用于生成配置的 upstream id")],
) -> None:
    """显示原配置和基于 upstream 生成的新配置。"""
    setup_target = _parse_target(target)
    if setup_target is None:
        return
    asyncio.run(_preview(setup_target, upstream_id))


@app.command("apply")
def apply_cmd(
    target: Annotated[str, typer.Argument(help="客户端: codex | claude | opencode")],
    upstream_id: Annotated[str, typer.Option("--upstream-id", help="用于生成配置的 upstream id")],
) -> None:
    """备份并写入本机客户端配置。"""
    setup_target = _parse_target(target)
    if setup_target is None:
        return
    asyncio.run(_apply(setup_target, upstream_id))


async def _preview(target: SetupTarget, upstream_id: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.setup_preview(target, upstream_id=upstream_id)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    except httpx.HTTPStatusError as e:
        Renderer.die(f"setup preview 失败: {e.response.status_code} {e.response.text}")
        return
    _render_preview(result)


async def _apply(target: SetupTarget, upstream_id: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.setup_apply(target, upstream_id=upstream_id)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    except httpx.HTTPStatusError as e:
        Renderer.die(f"setup apply 失败: {e.response.status_code} {e.response.text}")
        return
    Renderer.out(f"wrote {result.path}")
    if result.backup_path:
        Renderer.out(f"backup {result.backup_path}")


def _render_preview(result: SetupConfigOut) -> None:
    Renderer.out(f"target: {result.target}")
    Renderer.out(f"path: {result.path}")
    Renderer.out("\n--- original ---")
    Renderer.out(result.original or "(empty)")
    Renderer.out("\n--- generated ---")
    Renderer.out(result.generated)


def _parse_target(value: str) -> SetupTarget | None:
    normalized = value.lower()
    if normalized not in _ALLOWED_TARGETS:
        Renderer.die("target 必须是 codex / claude / opencode")
        return None
    return cast(SetupTarget, normalized)


def register(app_root: typer.Typer) -> None:
    """Register setup command group."""
    app_root.add_typer(app, name="setup")
