"""`rosetta models`: list configured models and their default upstream routing."""

from __future__ import annotations

import asyncio
from collections import defaultdict

import httpx
import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.upstreams import UpstreamOut


def models_cmd() -> None:
    """显示当前 upstream 配置支持的模型。"""
    asyncio.run(_models())


async def _models() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            upstreams = await client.list_upstreams()
            defaults = await client.list_model_defaults()
    except httpx.HTTPStatusError as e:
        Renderer.die(f"读取模型失败: {e.response.status_code} {e.response.text}")
        return
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")
        return

    groups: dict[str, list[UpstreamOut]] = defaultdict(list)
    for upstream in upstreams:
        model = (upstream.model or "").strip()
        if model:
            groups[model].append(upstream)

    if not groups:
        Renderer.out("no models configured")
        return

    rows: list[list[object]] = []
    for model, candidates in sorted(
        groups.items(),
        key=lambda item: (-(len(item[1]) > 1), item[0]),
    ):
        candidates.sort(key=lambda upstream: upstream.name)
        default_id = defaults.get(model)
        default = next((upstream for upstream in candidates if upstream.id == default_id), None)
        if len(candidates) == 1:
            status = "unique"
        elif default is not None:
            status = "configured"
        else:
            status = "required"
        rows.append(
            [
                model,
                status,
                default.name if default is not None else "-",
                ", ".join(upstream.name for upstream in candidates),
            ]
        )

    Renderer.table(
        ["model", "status", "default_upstream", "upstreams"],
        rows,
        no_wrap_columns={"status"},
        max_widths={"model": 36, "upstreams": 60},
    )


def register(app: typer.Typer) -> None:
    app.command("models")(models_cmd)