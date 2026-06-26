"""/admin/setup: preview and apply local client configuration files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, cast

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


class SetupConfigOut(BaseModel):
    target: SetupTarget
    path: str
    exists: bool
    original: str
    generated: str
    language: Literal["toml", "json"]
    backup_path: str | None = None
    model: str | None = None
    alias: str | None = None


@router.get("/setup/{target}/current", response_model=SetupConfigOut)
async def current_setup_config(
    target: SetupTarget,
    request: Request,
    repo: UpstreamRepoDep,
) -> SetupConfigOut:
    """读取本地配置文件,解析出当前 model 并展示 alias 信息。"""
    path = client_config_path(target, home=_config_home())
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    model_name = _parse_model_from_config(target, original)
    language: Literal["toml", "json"] = "toml" if target == "codex" else "json"

    if model_name:
        upstream, model_alias, _rewrite_model_to = await repo.select_upstream_by_model(model_name)
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
                model=upstream.model or model_name,
                alias=model_alias,
            )

    return SetupConfigOut(
        target=target,
        path=str(path),
        exists=path.exists(),
        original=original,
        generated="",
        language=language,
        model=model_name,
    )


@router.get("/setup/{target}/clear-preview", response_model=SetupConfigOut)
async def preview_clear_setup_config(target: SetupTarget) -> SetupConfigOut:
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
) -> SetupConfigOut:
    upstream, model_alias = await _resolve_setup_upstream(repo, model)

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
        model=model,
        alias=model_alias,
    )


@router.post("/setup/{target}/apply", response_model=SetupConfigOut)
async def apply_setup_config(
    target: SetupTarget,
    payload: SetupApplyIn,
    request: Request,
    repo: UpstreamRepoDep,
) -> SetupConfigOut:
    upstream, model_alias = await _resolve_setup_upstream(repo, payload.model)

    result = apply_client_config(
        target,
        cast(UpstreamLike, upstream),
        _rosetta_base_url(request),
        home=_config_home(),
        model_alias=model_alias,
    )
    return SetupConfigOut(
        target=result.target,
        path=str(result.path),
        exists=result.exists,
        original=result.original,
        generated=result.generated,
        language=result.language,
        backup_path=str(result.backup_path) if result.backup_path else None,
        model=payload.model,
        alias=model_alias,
    )


async def _resolve_setup_upstream(repo: UpstreamRepoDep, model: str) -> tuple[Upstream, str | None]:
    normalized = model.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="model 不能为空")

    upstream, alias, _rewrite_model_to = await repo.select_upstream_by_model(normalized)
    if upstream is not None:
        return upstream, alias

    # 如果 models 表不匹配,fallback 到 upstreams.model 精确匹配
    upstreams = await repo.get_by_model(normalized)
    if len(upstreams) == 1:
        return upstreams[0], None
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
    return os.environ.get("ROSETTA_SETUP_BASE_URL", str(request.base_url).rstrip("/"))


def _parse_model_from_config(target: SetupTarget, config_text: str) -> str | None:
    """从本地配置文件中解析出 model 字段。"""
    if not config_text:
        return None
    try:
        if target == "codex":
            import tomllib

            data = tomllib.loads(config_text)
            model = data.get("model")
            return str(model) if isinstance(model, str) else None

        import json

        raw = json.loads(config_text)
        if not isinstance(raw, dict):
            return None
        data = cast(dict[str, Any], raw)
        if target == "claude":
            raw_env = data.get("env", {})
            if isinstance(raw_env, dict):
                env = cast(dict[str, Any], raw_env)
                model = (
                    env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
                    or env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
                    or env.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
                )
                return model if isinstance(model, str) else None
        elif target == "opencode":
            model = data.get("model")
            if isinstance(model, str) and model.startswith("rosetta/"):
                return model[len("rosetta/") :]
            return model if isinstance(model, str) else None
    except Exception:
        pass
    return None