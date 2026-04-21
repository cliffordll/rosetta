"""/admin/logs:请求流水列表查询(阶段 4.2)。

v0.1 没 logger 真往 logs 表写入,因此本端点常态返空。保留是为让 CLI / GUI 的
"logs 列表"有统一接入点;等后续 logger 组件接入后直接生效。

查询参数:
- `limit`(默认 50,上限 500)
- `offset`(默认 0)
- `provider`:按 provider name 过滤(server 内部 JOIN 到 id)
- `since` / `until`:ISO 8601 时间戳过滤 `created_at`

响应每条:id / created_at / provider(name,可能为 null)/ model / input_tokens /
output_tokens / latency_ms / status / error。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import LogEntry, Provider
from rosetta.server.database.session import get_session

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_MAX_LIMIT = 500


class LogOut(BaseModel):
    id: int
    created_at: datetime
    provider: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    status: str
    error: str | None


@router.get("/logs", response_model=list[LogOut])
async def list_logs(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    provider: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[LogOut]:
    provider_id: int | None = None
    if provider is not None:
        result = await session.execute(select(Provider).where(Provider.name == provider))
        p = result.scalar_one_or_none()
        if p is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"provider '{provider}' 不存在",
            )
        provider_id = p.id

    filters: list[ColumnElement[bool]] = []
    if provider_id is not None:
        filters.append(LogEntry.provider_id == provider_id)
    if since is not None:
        filters.append(LogEntry.created_at >= since)
    if until is not None:
        filters.append(LogEntry.created_at <= until)

    stmt = (
        select(LogEntry, Provider)
        .outerjoin(Provider, LogEntry.provider_id == Provider.id)
        .order_by(LogEntry.created_at.desc(), LogEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if filters:
        stmt = stmt.where(and_(*filters))

    result = await session.execute(stmt)
    return [
        LogOut(
            id=entry.id,
            created_at=entry.created_at,
            provider=prov.name if prov is not None else None,
            model=entry.model,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            latency_ms=entry.latency_ms,
            status=entry.status,
            error=entry.error,
        )
        for entry, prov in result.all()
    ]
