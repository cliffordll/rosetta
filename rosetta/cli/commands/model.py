"""`rosetta model`: manage models, aliases, and upstream routing."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient


@dataclass(frozen=True)
class _ModelRow:
    name: str
    alias: str | None
    enabled: bool
    upstreams: str
    has_default: bool


class _ModelLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def alias(self) -> str | None: ...

    @property
    def enabled(self) -> bool: ...

    @property
    def upstreams(self) -> str: ...

    @property
    def has_default(self) -> bool: ...

app = typer.Typer(
    name="model",
    help="\u7ba1\u7406\u6a21\u578b\u3001\u522b\u540d\u548c upstream \u8def\u7531",
)


@app.command("list")
def list_cmd() -> None:
    """\u663e\u793a\u5f53\u524d\u6240\u6709\u6a21\u578b\u3002"""
    asyncio.run(_list_models())


@app.command("alias")
def alias_cmd(
    model_name: str = typer.Argument(help="\u6a21\u578b\u540d"),
    alias: str | None = typer.Argument(
        default=None, help="\u522b\u540d\uff08\u4f20\u7a7a\u5b57\u7b26\u4e32\u6e05\u7a7a\uff09"
    ),
) -> None:
    """\u8bbe\u7f6e\u6216\u6e05\u7a7a\u6a21\u578b\u522b\u540d\u3002"""
    asyncio.run(_set_alias(model_name, alias))


@app.command("enable")
def enable_cmd(
    model_name: str = typer.Argument(help="\u6a21\u578b\u540d"),
) -> None:
    """\u542f\u7528\u6a21\u578b\u3002"""
    asyncio.run(_set_enabled(model_name, True))


@app.command("disable")
def disable_cmd(
    model_name: str = typer.Argument(help="\u6a21\u578b\u540d"),
) -> None:
    """\u7981\u7528\u6a21\u578b\u3002"""
    asyncio.run(_set_enabled(model_name, False))


async def _list_models() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            if hasattr(client, "list_models"):
                models: Sequence[_ModelLike] = await client.list_models()
            else:
                upstreams = await client.list_upstreams()
                defaults = await client.list_model_defaults()
                models = _model_rows_from_upstreams(upstreams, defaults)
    except httpx.HTTPStatusError as e:
        Renderer.die(
            f"\u8bfb\u53d6\u6a21\u578b\u5217\u8868\u5931\u8d25: "
            f"{e.response.status_code} {e.response.text}"
        )
        return
    except RuntimeError as e:
        Renderer.die(f"server \u672a\u5c31\u7eea: {e}")
        return

    if not models:
        Renderer.out("no models configured")
        return

    rows = [
        [
            m.name,
            m.alias or "-",
            m.enabled,
            m.upstreams or "-",
            "\u2606" if m.has_default else "",
        ]
        for m in models
    ]

    Renderer.table(
        ["model", "alias", "enabled", "upstreams", "default"],
        rows,
        no_wrap_columns={"enabled", "default"},
    )


def _model_rows_from_upstreams(
    upstreams: Sequence[object], defaults: dict[str, str]
) -> list[_ModelRow]:
    grouped: dict[str, list[object]] = {}
    for upstream in upstreams:
        model = (getattr(upstream, "model", None) or "").strip()
        if not model:
            continue
        grouped.setdefault(model, []).append(upstream)
    rows: list[_ModelRow] = []
    for model, candidates in sorted(grouped.items()):
        names = ", ".join(sorted(str(getattr(item, "name", "")) for item in candidates))
        rows.append(
            _ModelRow(
                name=model,
                alias=None,
                enabled=True,
                upstreams=names,
                has_default=model in defaults,
            )
        )
    return rows


async def _set_alias(model_name: str, alias: str | None) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            result = await client.set_model_alias(model_name, alias)
    except httpx.HTTPStatusError as e:
        Renderer.die(
            f"\u8bbe\u7f6e\u522b\u540d\u5931\u8d25: {e.response.status_code} {e.response.text}"
        )
        return
    except RuntimeError as e:
        Renderer.die(f"server \u672a\u5c31\u7eea: {e}")
        return

    if alias:
        Renderer.out(f"model '{model_name}' alias -> {alias}")
    else:
        Renderer.out(f"model '{model_name}' alias cleared")
    Renderer.table(
        ["model", "alias", "enabled"],
        [[result.name, result.alias or "-", result.enabled]],
    )


async def _set_enabled(model_name: str, enabled: bool) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            await client.set_model_enabled(model_name, enabled)
    except httpx.HTTPStatusError as e:
        Renderer.die(
            f"\u8bbe\u7f6e\u72b6\u6001\u5931\u8d25: {e.response.status_code} {e.response.text}"
        )
        return
    except RuntimeError as e:
        Renderer.die(f"server \u672a\u5c31\u7eea: {e}")
        return

    status = "enabled" if enabled else "disabled"
    Renderer.out(f"model '{model_name}' {status}")


def register(parent: typer.Typer) -> None:
    parent.add_typer(app, name="model")
