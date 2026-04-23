"""/admin/providers 管理端点(v0 最小集:GET list、POST create、DELETE by id)。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.exc import IntegrityError

from rosetta.server.database.models import Provider
from rosetta.server.repository import ProviderRepoDep

router = APIRouter()

ProviderType = Literal["anthropic", "openai", "openrouter", "custom"]


class ProviderCreate(BaseModel):
    name: str
    type: ProviderType
    base_url: str | None = None
    api_key: str
    enabled: bool = True

    @model_validator(mode="after")
    def _custom_requires_base_url(self) -> ProviderCreate:
        if self.type == "custom" and not self.base_url:
            raise ValueError("type=custom 要求必须显式提供 base_url")
        return self


class ProviderOut(BaseModel):
    # 不暴露 api_key 字段
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    base_url: str | None
    enabled: bool
    created_at: datetime


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(repo: ProviderRepoDep) -> Sequence[Provider]:
    return await repo.list_all()


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderCreate, repo: ProviderRepoDep) -> Provider:
    try:
        return await repo.create(
            name=payload.name,
            type_=payload.type,
            base_url=payload.base_url,
            api_key=payload.api_key,
            enabled=payload.enabled,
        )
    except IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"provider name '{payload.name}' 已存在",
        ) from e


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: int, repo: ProviderRepoDep) -> Response:
    """删 provider(logs.provider_id 保留,字段 nullable)。

    历史 logs 保留 provider_id 作为死引用(FK 未强制),Logs 页显示时兜底。
    """
    provider = await repo.get_by_id(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider id={provider_id} 不存在",
        )
    await repo.delete(provider)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
