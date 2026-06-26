"""/admin/setup: preview and apply local client configuration files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepoDep
from rosetta.server.service.client_config import (
    UpstreamLike,
    apply_client_config,
    apply_client_config_clear,
    build_client_config_clear_preview,
    build_client_config_preview,
    client_config_path,
)

router = APIRouter()
SetupTarget = Literal["codex", "claude", "opencode"]


class SetupApplyIn(BaseModel):
    model: str
    model_alias: str | None = None


class SetupConfigOut(BaseModel):
    target: SetupTarget
    path: str
    exists: bool
    original: str
    generated: str
    language: Literal["toml", "json"]
    backup_path: str | None = None
    model: str | None = None
    model_alias: str | None = None


@router.get("/setup/{target}/current", response_model=SetupConfigOut)
async def current_setup_config(
    target: SetupTarget,
    request: Request,
    repo: UpstreamRepoDep,
) -> SetupConfigOut:
    """读取本地配置文件(不依赖 upstream)。"""
    path = client_config_path(target, home=_config_home())
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    language: Literal["toml", "json"] = "toml" if target == "codex" else "json"
    model_alias = await repo.setup_last_model_alias(target)
    if model_alias:
        upstream_id = await repo.setup_model_alias_upstream_id(target, model_alias)
        if upstream_id is not None:
            upstream = await repo.get_by_id(upstream_id)
            if upstream is not None and upstream.enabled:
                preview = build_client_config_preview(
                    target,
                    cast(UpstreamLike, upstream),
                    _rosetta_base_url(request),
                    home=_config_home(),
                    model_alias=model_alias,
                )
                return SetupConfigOut(
                    target=preview.target,
                    path=str(preview.path),
                    exists=preview.exists,
                    original=preview.original,
                    generated=preview.generated,
                    language=preview.language,
                    model=upstream.model,
                    model_alias=model_alias,
                )
    return SetupConfigOut(
        target=target,
        path=str(path),
        exists=path.exists(),
        original=original,
        generated="",
        language=language,
        model_alias=model_alias,
    )


@router.get("/setup/{target}/clear-preview", response_model=SetupConfigOut)
async def preview_clear_setup_config(target: SetupTarget) -> SetupConfigOut:
    """预览移除 Rosetta 客户端代理配置后的本地配置。"""
    preview = build_client_config_clear_preview(target, home=_config_home())
    return SetupConfigOut(
        target=preview.target,
        path=str(preview.path),
        exists=preview.exists,
        original=preview.original,
        generated=preview.generated,
        language=preview.language,
    )


@router.post("/setup/{target}/clear", response_model=SetupConfigOut)
async def clear_setup_config(target: SetupTarget) -> SetupConfigOut:
    """备份并移除 Rosetta 客户端代理配置。"""
    result = apply_client_config_clear(target, home=_config_home())
    return SetupConfigOut(
        target=result.target,
        path=str(result.path),
        exists=result.exists,
        original=result.original,
        generated=result.generated,
        language=result.language,
        backup_path=str(result.backup_path) if result.backup_path else None,
    )


@router.get("/setup/{target}/preview", response_model=SetupConfigOut)
async def preview_setup_config(
    target: SetupTarget,
    model: str,
    request: Request,
    repo: UpstreamRepoDep,
    model_alias: str | None = None,
) -> SetupConfigOut:
    upstream = await _resolve_setup_upstream(repo, model)
    normalized_alias = model_alias.strip() if model_alias else None

    preview = build_client_config_preview(
        target,
        cast(UpstreamLike, upstream),
        _rosetta_base_url(request),
        home=_config_home(),
        model_alias=normalized_alias,
    )
    return SetupConfigOut(
        target=preview.target,
        path=str(preview.path),
        exists=preview.exists,
        original=preview.original,
        generated=preview.generated,
        language=preview.language,
        model=upstream.model,
        model_alias=normalized_alias,
    )


@router.post("/setup/{target}/apply", response_model=SetupConfigOut)
async def apply_setup_config(
    target: SetupTarget,
    payload: SetupApplyIn,
    request: Request,
    repo: UpstreamRepoDep,
) -> SetupConfigOut:
    upstream = await _resolve_setup_upstream(repo, payload.model)

    model_alias = payload.model_alias.strip() if payload.model_alias else None
    result = apply_client_config(
        target,
        cast(UpstreamLike, upstream),
        _rosetta_base_url(request),
        home=_config_home(),
        model_alias=model_alias,
    )
    await repo.set_setup_last_model_alias(target, model_alias or "")
    if model_alias:
        await repo.set_setup_model_alias(target, upstream.id, model_alias)
    return SetupConfigOut(
        target=result.target,
        path=str(result.path),
        exists=result.exists,
        original=result.original,
        generated=result.generated,
        language=result.language,
        backup_path=str(result.backup_path) if result.backup_path else None,
        model=upstream.model,
        model_alias=model_alias,
    )


async def _resolve_setup_upstream(repo: UpstreamRepoDep, model: str) -> Upstream:
    normalized = model.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="model 不能为空")

    default_id = await repo.default_model_upstream_id(normalized)
    if default_id is not None:
        upstream = await repo.get_by_id(default_id)
        if upstream is not None and upstream.enabled:
            return upstream

    upstreams = await repo.get_by_model(normalized)
    if len(upstreams) == 1:
        return upstreams[0]
    if not upstreams:
        raise HTTPException(status_code=404, detail=f"model={normalized!r} 没有对应 upstream")
    raise HTTPException(
        status_code=400,
        detail=f"model={normalized!r} 匹配到多个 upstream,请先设置该 model 的默认 upstream",
    )


def _config_home() -> Path | None:
    override = os.environ.get("ROSETTA_SETUP_CONFIG_HOME")
    return Path(override) if override else None


def _rosetta_base_url(request: Request) -> str:
    # The browser and CLI connect to the local admin API; generated client configs
    # should point back to this same Rosetta server by default.
    return os.environ.get("ROSETTA_SETUP_BASE_URL", str(request.base_url).rstrip("/"))