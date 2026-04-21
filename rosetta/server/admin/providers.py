"""/admin/providers 管理端点(v0 最小集:GET list、POST create)。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider
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
