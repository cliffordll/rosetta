"""/admin/routes:路由规则查询 + 批量替换(阶段 3.1)。

设计要点
-------
- GET 返回当前全量规则,按 (priority ASC, id ASC) 排序,与数据面匹配顺序一致
- PUT 语义是 **替换**(不是 upsert):整表 delete + 批量 insert,事务内完成
- 请求/响应里 provider 用 **name** 引用,server 查 DB 反解出 id
- payload 里引用到不存在的 provider → 整批 400(不落部分成功)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider, Route
from rosetta.server.database.session import get_session

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class RouteIn(BaseModel):
    model_glob: str
    provider: str  # 按 name 引用
    priority: int = 0


class RouteOut(BaseModel):
    id: int
    model_glob: str
    provider: str
    priority: int


async def _list_routes_joined(session: AsyncSession) -> list[RouteOut]:
    result = await session.execute(
        select(Route, Provider)
        .join(Provider, Route.provider_id == Provider.id)
        .order_by(Route.priority, Route.id)
    )
    return [
        RouteOut(
            id=route.id,
            model_glob=route.model_glob,
            provider=provider.name,
            priority=route.priority,
        )
        for route, provider in result.all()
    ]


@router.get("/routes", response_model=list[RouteOut])
async def list_routes(session: SessionDep) -> list[RouteOut]:
    return await _list_routes_joined(session)


@router.put("/routes", response_model=list[RouteOut])
async def replace_routes(payload: list[RouteIn], session: SessionDep) -> list[RouteOut]:
    # 一次性把 payload 引用的所有 provider name 查出来,缺名直接 400
    names = {r.provider for r in payload}
    providers: dict[str, Provider] = {}
    if names:
        result = await session.execute(select(Provider).where(Provider.name.in_(names)))
        providers = {p.name: p for p in result.scalars().all()}

    missing = sorted(n for n in names if n not in providers)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"provider 不存在: {', '.join(missing)}",
        )

    # 事务:清表 + 插新(commit 原子替换)
    await session.execute(delete(Route))
    for r in payload:
        session.add(
            Route(
                model_glob=r.model_glob,
                provider_id=providers[r.provider].id,
                priority=r.priority,
            )
        )
    await session.commit()

    return await _list_routes_joined(session)
