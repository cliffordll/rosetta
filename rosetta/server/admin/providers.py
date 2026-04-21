"""/admin/providers 管理端点(v0 最小集:GET list、POST create、DELETE by id)。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider, Route
from rosetta.server.database.session import get_session

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


SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(session: SessionDep) -> Sequence[Provider]:
    result = await session.execute(select(Provider).order_by(Provider.id))
    return result.scalars().all()


@router.post("/providers", response_model=ProviderOut, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderCreate, session: SessionDep) -> Provider:
    provider = Provider(
        name=payload.name,
        type=payload.type,
        base_url=payload.base_url,
        api_key=payload.api_key,
        enabled=payload.enabled,
    )
    session.add(provider)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"provider name '{payload.name}' 已存在",
        ) from e
    await session.refresh(provider)
    return provider


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: int, session: SessionDep) -> Response:
    """删 provider;连带删引用它的 routes(logs.provider_id 保留,字段 nullable)。

    级联策略见 DESIGN.md §8.1:v0 直接级联,避免 UI 多一步"先清路由";
    历史 logs 保留 provider_id 作为死引用(FK 未强制),Logs 页显示时兜底。
    """
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider id={provider_id} 不存在",
        )
    await session.execute(delete(Route).where(Route.provider_id == provider_id))
    await session.delete(provider)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
