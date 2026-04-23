"""/admin/upstreams 管理端点(v0 最小集:GET list、POST create、DELETE by id)。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import IntegrityError

from rosetta.server.database.models import Upstream, UpstreamProtocol, UpstreamProvider
from rosetta.server.repository import UpstreamRepoDep

router = APIRouter()


class UpstreamCreate(BaseModel):
    name: str
    protocol: UpstreamProtocol
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


@router.get("/upstreams", response_model=list[UpstreamOut])
async def list_upstreams(repo: UpstreamRepoDep) -> Sequence[Upstream]:
    return await repo.list_all()


@router.post(
    "/upstreams", response_model=UpstreamOut, status_code=status.HTTP_201_CREATED
)
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
