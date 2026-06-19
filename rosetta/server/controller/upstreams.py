"""/admin/upstreams 管理端点:list / create / update / delete / set-default / restore-mock。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from rosetta.server.database.models import UpstreamNativeApi, UpstreamProvider
from rosetta.server.repository import UpstreamRepoDep
from rosetta.server.service.forwarder import forwarder

router = APIRouter()

# 用户可创建的 native_api 值域:不含 `any`(any 专供 mock 占位,DB seed / restore-mock 才写)
UpstreamNativeApiCreatable = Literal["messages", "completions", "responses"]


class UpstreamCreate(BaseModel):
    # `model` 字段名与 Pydantic v2 内部 `model_*` 命名空间无前缀冲突,
    # 但要显式关掉 protected_namespaces 抑制 warning
    model_config = ConfigDict(protected_namespaces=())

    name: str
    native_api: UpstreamNativeApiCreatable
    provider: UpstreamProvider = "custom"
    base_url: str
    api_key: str | None = None
    model: str | None = None
    enabled: bool = True


class UpstreamUpdate(BaseModel):
    """部分更新:所有字段 Optional;`exclude_unset=True` 区分"未传"和"传 null"。

    - 任何字段未传 → 不动
    - `api_key` / `model` 显式传 `null` → 清空该字段
    - `native_api` 改了不影响 per-server_api default(由 settings 表独立维护)
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str | None = None
    native_api: UpstreamNativeApiCreatable | None = None
    provider: UpstreamProvider | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    enabled: bool | None = None


class UpstreamOut(BaseModel):
    # 不暴露 api_key 字段
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    name: str
    native_api: UpstreamNativeApi
    provider: str
    base_url: str
    model: str | None
    enabled: bool
    is_default: bool = False
    created_at: datetime
    api_key: str | None = None


class RestoreMockOut(BaseModel):
    """restore-mock 结果:`created` 表"本次是否真的插入";幂等场景可能为 False。"""

    created: bool
    upstream: UpstreamOut


class UpstreamDefaultsOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    global_: str | None = Field(default=None, alias="global")
    messages: str | None = None
    completions: str | None = None
    responses: str | None = None


class UpstreamProbeOut(BaseModel):
    ok: bool
    upstream_id: str
    upstream_name: str
    native_api: str
    status_code: int | None
    category: Literal["ok", "network", "auth", "model", "upstream_error", "invalid_response", "config"]
    summary: str
    detail: str | None = None


@router.get("/upstreams", response_model=list[UpstreamOut])
async def list_upstreams(
    repo: UpstreamRepoDep,
    server_api: Annotated[UpstreamNativeApiCreatable, Query()] = "messages",
) -> Sequence[UpstreamOut]:
    upstreams = await repo.list_all()
    default_id = await repo.default_upstream_id(server_api)
    return [
        UpstreamOut.model_validate(u).model_copy(update={"is_default": u.id == default_id})
        for u in upstreams
    ]


@router.get("/upstreams/defaults", response_model=UpstreamDefaultsOut)
async def get_upstream_defaults(repo: UpstreamRepoDep) -> UpstreamDefaultsOut:
    return UpstreamDefaultsOut.model_validate(await repo.list_defaults())


@router.post("/upstreams", response_model=UpstreamOut, status_code=status.HTTP_201_CREATED)
async def create_upstream(
    payload: UpstreamCreate,
    repo: UpstreamRepoDep,
    server_api: Annotated[UpstreamNativeApiCreatable, Query()] = "messages",
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
    default_id = await repo.default_upstream_id(server_api)
    return UpstreamOut.model_validate(upstream).model_copy(
        update={"is_default": upstream.id == default_id}
    )


@router.put("/upstreams/{upstream_id}", response_model=UpstreamOut)
async def update_upstream(
    upstream_id: str,
    payload: UpstreamUpdate,
    repo: UpstreamRepoDep,
    server_api: Annotated[UpstreamNativeApiCreatable, Query()] = "messages",
) -> UpstreamOut:
    """部分更新 upstream;未传字段不动,`api_key`/`model` 传 null 显式清空。

    `native_api` 改了不影响 per-server_api / global default(由 settings 表独立维护)。
    """
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="UpstreamUpdate 必须至少提供一个字段",
        )
    # api_key / model 要区分"未传(保留)"和"传 null(清空)";其他字段用 None=未传
    api_key_arg = fields.get("api_key", ...)
    model_arg = fields.get("model", ...)
    try:
        upstream = await repo.update(
            upstream_id,
            name=fields.get("name"),
            native_api=fields.get("native_api"),
            provider=fields.get("provider"),
            base_url=fields.get("base_url"),
            api_key=api_key_arg,  # type: ignore[arg-type]
            model=model_arg,  # type: ignore[arg-type]
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
    default_id = await repo.default_upstream_id(server_api)
    return UpstreamOut.model_validate(upstream).model_copy(
        update={"is_default": upstream.id == default_id}
    )


@router.post("/upstreams/restore-mock", response_model=RestoreMockOut)
async def restore_mock_upstream(
    repo: UpstreamRepoDep,
    force: bool = False,
    server_api: Annotated[UpstreamNativeApiCreatable, Query()] = "messages",
) -> RestoreMockOut:
    """恢复内置 mock upstream。幂等;`?force=true` 则先删除再重建。

    用途:开发时误删 mock / 想把它恢复到出厂配置。路由不在 `/{upstream_id}` 之前
    注册,避免被通配路径吞掉。
    """
    created, upstream = await repo.restore_mock(force=force)
    default_id = await repo.default_upstream_id(server_api)
    return RestoreMockOut(
        created=created,
        upstream=UpstreamOut.model_validate(upstream).model_copy(
            update={"is_default": upstream.id == default_id}
        ),
    )


@router.put("/upstreams/{name}/default", response_model=UpstreamOut)
async def set_default_upstream(
    name: str,
    repo: UpstreamRepoDep,
    server_api: Annotated[UpstreamNativeApiCreatable | None, Query()] = None,
) -> UpstreamOut:
    """把 `name` 设为 default(写入 settings 表)。

    - `?server_api=messages` → 仅设 messages 的 default
    - 不传 `server_api` → 设 global default,作为所有 server_api 的兜底

    路径用 `name` 而非 `id`:CLI / GUI 的"设为默认"是按名字操作的高频动作,绕
    `id` 反而多一步翻译;name 有 UNIQUE 约束,语义无歧义。
    """
    try:
        upstream = await repo.set_default(name, server_api=server_api)
    except LookupError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream name='{name}' 不存在",
        ) from e
    return UpstreamOut.model_validate(upstream).model_copy(update={"is_default": True})


@router.post("/upstreams/{upstream_id}/test", response_model=UpstreamProbeOut)
async def test_upstream(upstream_id: str, repo: UpstreamRepoDep) -> UpstreamProbeOut:
    upstream = await repo.get_by_id(upstream_id)
    if upstream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream id={upstream_id} 不存在",
        )
    return UpstreamProbeOut.model_validate((await forwarder.probe_upstream(upstream)).__dict__)


@router.delete("/upstreams/{upstream_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upstream(upstream_id: str, repo: UpstreamRepoDep) -> Response:
    """删 upstream(logs.upstream_id 保留,字段 nullable)。

    历史 logs 保留 upstream_id 作为死引用(FK 未强制),Logs 页显示时兜底。
    """
    upstream = await repo.get_by_id(upstream_id)
    if upstream is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upstream id={upstream_id} 不存在",
        )
    await repo.delete(upstream)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
