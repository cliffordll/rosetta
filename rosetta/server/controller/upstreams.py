"""/admin/upstreams 管理端点(v0 最小集:GET list、POST create、DELETE by id)。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError

from rosetta.server.database.models import Upstream, UpstreamProvider
from rosetta.server.repository import UpstreamRepoDep

router = APIRouter()

# 用户可创建的 protocol 值域:不含 `any`(any 专供 mock 占位,DB seed / restore-mock 才写)
UpstreamProtocolCreatable = Literal["messages", "completions", "responses"]


class UpstreamCreate(BaseModel):
    name: str
    protocol: UpstreamProtocolCreatable
    provider: UpstreamProvider = "custom"
    base_url: str
    api_key: str | None = None
    enabled: bool = True


class UpstreamOut(BaseModel):
    # 不暴露 api_key 字段
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    protocol: str
    provider: str
    base_url: str
    enabled: bool
    created_at: datetime


class RestoreMockOut(BaseModel):
    """restore-mock 结果:`created` 表"本次是否真的插入";幂等场景可能为 False。"""

    created: bool
    upstream: UpstreamOut


@router.get("/upstreams", response_model=list[UpstreamOut])
async def list_upstreams(repo: UpstreamRepoDep) -> Sequence[Upstream]:
    return await repo.list_all()


@router.post("/upstreams", response_model=UpstreamOut, status_code=status.HTTP_201_CREATED)
async def create_upstream(payload: UpstreamCreate, repo: UpstreamRepoDep) -> Upstream:
    try:
        return await repo.create(
            name=payload.name,
            protocol=payload.protocol,
            provider=payload.provider,
            base_url=payload.base_url,
            api_key=payload.api_key,
            enabled=payload.enabled,
        )
    except IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"upstream name '{payload.name}' 已存在",
        ) from e


@router.post("/upstreams/restore-mock", response_model=RestoreMockOut)
async def restore_mock_upstream(repo: UpstreamRepoDep, force: bool = False) -> RestoreMockOut:
    """恢复内置 mock upstream。幂等;`?force=true` 则先删除再重建。

    用途:开发时误删 mock / 想把它恢复到出厂配置。路由不在 `/{upstream_id}` 之前
    注册,避免被通配路径吞掉。
    """
    created, upstream = await repo.restore_mock(force=force)
    return RestoreMockOut(
        created=created,
        upstream=UpstreamOut.model_validate(upstream),
    )


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
