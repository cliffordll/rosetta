"""/admin/setup: preview and apply local client configuration files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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
    upstream_id: str


class SetupConfigOut(BaseModel):
    target: SetupTarget
    path: str
    exists: bool
    original: str
    generated: str
    language: Literal["toml", "json"]
    backup_path: str | None = None


@router.get("/setup/{target}/current", response_model=SetupConfigOut)
async def current_setup_config(
    target: SetupTarget,
    request: Request,
) -> SetupConfigOut:
    """读取本地配置文件(不依赖 upstream)。"""
    path = client_config_path(target, home=_config_home())
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    return SetupConfigOut(
        target=target,
        path=str(path),
        exists=path.exists(),
        original=original,
        generated="",
        language="toml" if target == "codex" else "json",
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
    upstream_id: str,
    request: Request,
    repo: UpstreamRepoDep,
) -> SetupConfigOut:
    upstream = await repo.get_by_id(upstream_id)
    if upstream is None:
        raise HTTPException(status_code=404, detail=f"upstream id={upstream_id} 不存在")

    preview = build_client_config_preview(
        target,
        cast(UpstreamLike, upstream),
        _rosetta_base_url(request),
        home=_config_home(),
    )
    return SetupConfigOut(
        target=preview.target,
        path=str(preview.path),
        exists=preview.exists,
        original=preview.original,
        generated=preview.generated,
        language=preview.language,
    )


@router.post("/setup/{target}/apply", response_model=SetupConfigOut)
async def apply_setup_config(
    target: SetupTarget,
    payload: SetupApplyIn,
    request: Request,
    repo: UpstreamRepoDep,
) -> SetupConfigOut:
    upstream = await repo.get_by_id(payload.upstream_id)
    if upstream is None:
        raise HTTPException(status_code=404, detail=f"upstream id={payload.upstream_id} 不存在")

    result = apply_client_config(
        target,
        cast(UpstreamLike, upstream),
        _rosetta_base_url(request),
        home=_config_home(),
    )
    return SetupConfigOut(
        target=result.target,
        path=str(result.path),
        exists=result.exists,
        original=result.original,
        generated=result.generated,
        language=result.language,
        backup_path=str(result.backup_path) if result.backup_path else None,
    )


def _config_home() -> Path | None:
    override = os.environ.get("ROSETTA_SETUP_CONFIG_HOME")
    return Path(override) if override else None


def _rosetta_base_url(request: Request) -> str:
    # The browser and CLI connect to the local admin API; generated client configs
    # should point back to this same Rosetta server by default.
    return os.environ.get("ROSETTA_SETUP_BASE_URL", str(request.base_url).rstrip("/"))
