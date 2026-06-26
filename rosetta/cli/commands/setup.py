"""`rosetta setup` commands: preview, apply, and clear local client config files."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from typing import Annotated, cast

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.setup import SetupConfigOut, SetupTarget
from rosetta.server.controller.upstreams import UpstreamOut

_ALLOWED_TARGETS = {"codex", "claude", "opencode"}
_ALLOWED_COMMAND_KINDS = {"powershell", "export", "cli"}

app = typer.Typer(
    help="客户端本机配置预览和写入",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command("preview")
def preview_cmd(
    target: Annotated[str, typer.Argument(help="客户端: codex | claude | opencode")],
    model: Annotated[str, typer.Option("--model", help="用于生成配置的 model")],
) -> None:
    """显示原配置和基于 upstream 生成的新配置。"""
    setup_target = _parse_target(target)
    if setup_target is None:
        return
    asyncio.run(_preview(setup_target, model))


@app.command("apply")
def apply_cmd(
    target: Annotated[str, typer.Argument(help="客户端: codex | claude | opencode")],
    model: Annotated[str, typer.Option("--model", help="用于生成配置的 model")],
) -> None:
    """备份并写入本机客户端配置。"""
    setup_target = _parse_target(target)
    if setup_target is None:
        return
    asyncio.run(_apply(setup_target, model))


@app.command("clear")
def clear_cmd(
    target: Annotated[str, typer.Argument(help="客户端: codex | claude | opencode")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="确认移除 Rosetta 客户端配置"),
    ] = False,
) -> None:
    """备份并移除本机客户端中的 Rosetta 配置。"""
    setup_target = _parse_target(target)
    if setup_target is None:
        return
    if not yes:
        Renderer.die("clear setup config 需要显式传 --yes")
        return
    asyncio.run(_clear(setup_target))


@app.command("command")
def command_cmd(
    target: Annotated[str, typer.Argument(help="客户端: codex | claude | opencode")],
    model: Annotated[
        str | None,
        typer.Option("--model", help="用于读取 api_key 的 model;省略则使用 rosetta-local"),
    ] = None,
    kind: Annotated[
        str,
        typer.Option("--kind", help="命令类型: powershell | export | cli"),
    ] = "powershell",
    copy: Annotated[bool, typer.Option("--copy", help="复制到系统剪贴板")] = False,
) -> None:
    """输出或复制 Setup 页底部的 PowerShell/export/CLI 命令。"""
    setup_target = _parse_target(target)
    if setup_target is None:
        return
    command_kind = _parse_command_kind(kind)
    if command_kind is None:
        return
    asyncio.run(_command(setup_target, model=model, kind=command_kind, copy=copy))


async def _command(
    target: SetupTarget,
    *,
    model: str | None,
    kind: str,
    copy: bool,
) -> None:
    api_key = "rosetta-local"
    if model:
        try:
            async with ProxyClient.discover_session(spawn_if_missing=False) as client:
                upstreams = await client.list_upstreams()
                defaults = (
                    await client.list_model_defaults()
                    if hasattr(client, "list_model_defaults")
                    else {}
                )
        except RuntimeError as e:
            Renderer.die(f"server 未就绪: {e}")
            return
        except httpx.HTTPStatusError as e:
            Renderer.die(f"upstream 列表读取失败: {e.response.status_code} {e.response.text}")
            return
        upstream = _find_upstream_by_model(upstreams, model, defaults.get(model))
        if upstream is None:
            Renderer.die(f"model={model!r} 没有可用默认 upstream")
            return
        api_key = upstream.api_key or "rosetta-local"

    command = _setup_command(target, kind=kind, api_key=api_key)
    if copy:
        try:
            _copy_to_clipboard(command)
        except RuntimeError as e:
            Renderer.die(str(e))
            return
        Renderer.out("copied command")
    else:
        Renderer.out(command)


async def _preview(target: SetupTarget, model: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.setup_preview(target, model=model)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    except httpx.HTTPStatusError as e:
        Renderer.die(f"setup preview 失败: {e.response.status_code} {e.response.text}")
        return
    _render_preview(result)


async def _apply(target: SetupTarget, model: str) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.setup_apply(target, model=model)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    except httpx.HTTPStatusError as e:
        Renderer.die(f"setup apply 失败: {e.response.status_code} {e.response.text}")
        return
    Renderer.out(f"wrote {result.path}")
    if result.backup_path:
        Renderer.out(f"backup {result.backup_path}")


async def _clear(target: SetupTarget) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.setup_clear(target)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return
    except httpx.HTTPStatusError as e:
        Renderer.die(f"setup clear 失败: {e.response.status_code} {e.response.text}")
        return
    Renderer.out(f"cleared {result.path}")
    if result.backup_path:
        Renderer.out(f"backup {result.backup_path}")


def _setup_command(target: SetupTarget, *, kind: str, api_key: str) -> str:
    if kind == "powershell":
        return f'$env:{_api_key_env(target)}="{api_key}"'
    if kind == "export":
        return f"export {_api_key_env(target)}={_shell_quote(api_key)}"
    if kind == "cli":
        return _cli_command(target)
    raise ValueError(f"unsupported setup command kind: {kind}")


def _api_key_env(target: SetupTarget) -> str:
    if target == "claude":
        return "ANTHROPIC_API_KEY"
    return "OPENAI_API_KEY"


def _cli_command(target: SetupTarget) -> str:
    if target == "codex":
        return "codex --oss --local-provider rosetta"
    if target == "claude":
        return "claude"
    if target == "opencode":
        return "opencode"
    raise ValueError(f"unsupported setup target: {target}")


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _find_upstream_by_model(
    upstreams: list[UpstreamOut], model: str, default_upstream_id: str | None = None
) -> UpstreamOut | None:
    matches = [item for item in upstreams if item.enabled and item.model == model]
    if default_upstream_id is not None:
        return next((item for item in matches if item.id == default_upstream_id), None)
    return matches[0] if len(matches) == 1 else None


def _copy_to_clipboard(text: str) -> None:
    if sys.platform == "win32":
        _run_clipboard_command(["clip"], text)
        return
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        _run_clipboard_command(["pbcopy"], text)
        return
    for command in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        if shutil.which(command[0]):
            _run_clipboard_command(command, text)
            return
    raise RuntimeError("找不到可用的剪贴板命令")


def _run_clipboard_command(command: list[str], text: str) -> None:
    try:
        subprocess.run(command, input=text, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"复制到剪贴板失败: {e}") from e


def _render_preview(result: SetupConfigOut) -> None:
    Renderer.out(f"target: {result.target}")
    Renderer.out(f"path: {result.path}")
    model = getattr(result, "model", None)
    model_alias = getattr(result, "alias", None)
    if model:
        Renderer.out(f"model: {model}")
    if model_alias:
        Renderer.out(f"model_alias: {model_alias}")
    Renderer.out("\n--- original ---")
    Renderer.raw(result.original or "(empty)")
    Renderer.out("\n--- generated ---")
    Renderer.raw(result.generated)


def _parse_target(value: str) -> SetupTarget | None:
    normalized = value.lower()
    if normalized not in _ALLOWED_TARGETS:
        Renderer.die("target 必须是 codex / claude / opencode")
        return None
    return cast(SetupTarget, normalized)


def _parse_command_kind(value: str) -> str | None:
    normalized = value.lower()
    if normalized not in _ALLOWED_COMMAND_KINDS:
        Renderer.die("kind 必须是 powershell / export / cli")
        return None
    return normalized


def register(app_root: typer.Typer) -> None:
    """Register setup command group."""
    app_root.add_typer(app, name="setup")
