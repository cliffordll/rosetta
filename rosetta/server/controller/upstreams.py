"""/admin/upstreams 管理端点。"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from rosetta.server.database.models import UpstreamNativeApi, UpstreamProvider
from rosetta.server.repository import UpstreamRepoDep
from rosetta.server.service.forwarder import forwarder

router = APIRouter()

_test_results: dict[str, str] = {}

UpstreamNativeApiCreatable = Literal["messages", "completions", "responses"]


class UpstreamCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str
    native_api: UpstreamNativeApiCreatable
    provider: UpstreamProvider = "custom"
    base_url: str
    api_key: str | None = None
    model: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model 不能为空")
        return value


class UpstreamUpdate(BaseModel):
    """部分更新:所有字段 Optional;`exclude_unset=True` 区分"未传"和"传 null"。

    - 任何字段未传 -> 不动
    - `api_key` 显式传 `null` -> 清空该字段
    - `model` 传值可更新,但不能传 `null` 或空字符串
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str | None = None
    native_api: UpstreamNativeApiCreatable | None = None
    provider: UpstreamProvider | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    enabled: bool | None = None

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("model 不能为空")
        return value


class UpstreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    name: str
    native_api: UpstreamNativeApi
    provider: str
    base_url: str
    model: str | None
    enabled: bool
    created_at: datetime
    api_key: str | None = None
    test_result: str | None = None


class ModelOut(BaseModel):
    id: str
    name: str
    alias: str | None = None
    enabled: bool = True
    upstreams: str = ""
    has_default: bool = False


class ModelAliasIn(BaseModel):
    alias: str | None = None


class ModelEnabledIn(BaseModel):
    enabled: bool


class RestoreMockOut(BaseModel):
    created: bool
    upstream: UpstreamOut


class UpstreamProbeOut(BaseModel):
    ok: bool
    upstream_id: str
    upstream_name: str
    native_api: str
    status_code: int | None
    category: Literal[
        "ok",
        "network",
        "auth",
        "model",
        "upstream_error",
        "invalid_response",
        "config",
    ]
    summary: str
    detail: str | None = None


@router.get("/upstreams", response_model=list[UpstreamOut])
async def list_upstreams(
    repo: UpstreamRepoDep,
) -> Sequence[UpstreamOut]:
    upstreams = await repo.list_all()
    return [
        UpstreamOut(
            **UpstreamOut.model_validate(u).model_dump(exclude={"test_result"}),
            test_result=_test_results.get(u.id),
        )
        for u in upstreams
    ]


@router.get("/upstreams/model-defaults", response_model=dict[str, str])
async def get_model_defaults(repo: UpstreamRepoDep) -> dict[str, str]:
    """返回 model -> upstream id 的默认路由映射。"""
    return await repo.list_model_defaults()


@router.get("/models", response_model=list[ModelOut])
async def list_models(repo: UpstreamRepoDep) -> list[ModelOut]:
    models = await repo.list_models()
    return [ModelOut.model_validate(m) for m in models]


@router.put("/models/{model_name}/alias", response_model=ModelOut)
async def set_model_alias(
    model_name: str, payload: ModelAliasIn, repo: UpstreamRepoDep
) -> ModelOut:
    try:
        await repo.set_model_alias(model_name, payload.alias)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    models = await repo.list_models()
    for m in models:
        if m["name"] == model_name:
            return ModelOut.model_validate(m)
    raise HTTPException(status_code=404, detail=f"model={model_name!r} not found after update")


@router.put("/models/{model_name}/enabled", response_model=ModelOut)
async def set_model_enabled(
    model_name: str, payload: ModelEnabledIn, repo: UpstreamRepoDep
) -> ModelOut:
    try:
        await repo.set_model_enabled(model_name, payload.enabled)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    models = await repo.list_models()
    for m in models:
        if m["name"] == model_name:
            return ModelOut.model_validate(m)
    raise HTTPException(status_code=404, detail=f"model={model_name!r} not found after update")


@router.post("/upstreams", response_model=UpstreamOut, status_code=status.HTTP_201_CREATED)
async def create_upstream(
    payload: UpstreamCreate,
    repo: UpstreamRepoDep,
) -> UpstreamOut:
    try:
        upstream = await repo.create(
            name=payload.name,
            native_api=payload.native_api,
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
            model=payload.model,
            enabled=payload.enabled,
        )
    except IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"upstream name '{payload.name}' 已存在",
        ) from e
    # Auto-create model and link
    model_id = await repo.get_or_create_model(payload.model)
    await repo.set_upstream_model(upstream.id, model_id, is_default=True)
    await repo.unset_other_defaults(payload.model, upstream.id)
    return UpstreamOut.model_validate(upstream)


@router.put("/upstreams/{upstream_id}", response_model=UpstreamOut)
async def update_upstream(
    upstream_id: str,
    payload: UpstreamUpdate,
    repo: UpstreamRepoDep,
) -> UpstreamOut:
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UpstreamUpdate 必须至少提供一个字段",
        )
    api_key_arg = fields.get("api_key", ...)
    model_arg = fields.get("model", ...)
    if model_arg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="model 不能为空",
        )
    try:
        upstream = await repo.update(
            upstream_id,
            name=fields.get("name"),
            native_api=fields.get("native_api"),
            provider=fields.get("provider"),
            base_url=fields.get("base_url"),
            api_key=api_key_arg,
            model=model_arg,
            enabled=fields.get("enabled"),
        )
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream id={upstream_id} 不存在",
        ) from e
    except IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"upstream name '{fields.get('name')}' 已存在",
        ) from e

    # If model was updated, sync upstream_models
    if model_arg is not ... and model_arg is not None:
        model_id = await repo.get_or_create_model(model_arg)
        await repo.set_upstream_model(upstream_id, model_id, is_default=True)
        await repo.unset_other_defaults(model_arg, upstream_id)

    return UpstreamOut.model_validate(upstream)


@router.post("/upstreams/restore-mock", response_model=RestoreMockOut)
async def restore_mock_upstream(
    repo: UpstreamRepoDep,
    force: bool = False,
) -> RestoreMockOut:
    created, upstream = await repo.restore_mock(force=force)
    return RestoreMockOut(
        created=created,
        upstream=UpstreamOut.model_validate(upstream),
    )


@router.put("/upstreams/{upstream_id}/model-default", response_model=UpstreamOut)
async def set_model_default_upstream(
    upstream_id: str,
    repo: UpstreamRepoDep,
    model: Annotated[str, Query(min_length=1)],
) -> UpstreamOut:
    upstream = await repo.get_by_id(upstream_id)
    if upstream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream id={upstream_id} 不存在",
        )
    model_id = await repo.get_or_create_model(model)
    await repo.set_upstream_model(upstream_id, model_id, is_default=True)
    await repo.unset_other_defaults(model, upstream_id)
    return UpstreamOut.model_validate(upstream)


@router.post("/upstreams/{upstream_id}/test", response_model=UpstreamProbeOut)
async def test_upstream(upstream_id: str, repo: UpstreamRepoDep) -> UpstreamProbeOut:
    upstream = await repo.get_by_id(upstream_id)
    if upstream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream id={upstream_id} 不存在",
        )
    result = UpstreamProbeOut.model_validate((await forwarder.probe_upstream(upstream)).__dict__)
    _test_results[upstream_id] = "ok" if result.ok else "fail"
    return result


@router.delete("/upstreams/{upstream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upstream(upstream_id: str, repo: UpstreamRepoDep) -> Response:
    upstream = await repo.get_by_id(upstream_id)
    if upstream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream id={upstream_id} 不存在",
        )
    await repo.delete(upstream)
    _test_results.pop(upstream_id, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ClientGuideOut(BaseModel):
    client: str
    content: str


_CLIENT_GUIDES = {
    "codex": "codex.md",
    "claude": "claude.md",
    "opencode": "opencode.md",
    "readme": "readme.md",
}


def _client_guide_path(filename: str) -> Path | None:
    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if isinstance(bundle_root, str):
        candidates.append(Path(bundle_root) / "docs" / "setup" / filename)
    candidates.append(Path(__file__).resolve().parents[3] / "docs" / "setup" / filename)

    for path in candidates:
        if path.is_file():
            return path
    return None


@router.get("/upstreams/guide/{client}")
async def get_client_guide(client: str) -> ClientGuideOut:
    filename = _CLIENT_GUIDES.get(client.lower())
    if filename is None:
        raise HTTPException(status_code=404, detail=f"unknown client: {client}")
    doc_path = _client_guide_path(filename)
    if doc_path is None:
        raise HTTPException(status_code=404, detail="guide file not found")
    content = doc_path.read_text(encoding="utf-8")
    return ClientGuideOut(client=client.lower(), content=content)
