"""/admin/logs:请求流水列表查询(阶段 4.2)。

v0.1 没 logger 真往 logs 表写入,因此本端点常态返空。保留是为让 CLI / GUI 的
"logs 列表"有统一接入点;等后续 logger 组件接入后直接生效。

查询参数:
- `limit`(默认 50,上限 500)
- `offset`(默认 0)
- `upstream`:按 upstream name 过滤(server 内部 JOIN 到 id)
- `since` / `until`:ISO 8601 时间戳过滤 `created_at`

响应每条:id / created_at / upstream(name,可能为 null)/ model / input_tokens /
output_tokens / latency_ms / status / error。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from rosetta.server.repository import LogRepoDep, UpstreamRepoDep

router = APIRouter()

_MAX_LIMIT = 500


class LogOut(BaseModel):
    id: str
    created_at: datetime
    upstream: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    status: str
    error: str | None


@router.get("/logs", response_model=list[LogOut])
async def list_logs(
    log_repo: LogRepoDep,
    upstream_repo: UpstreamRepoDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    upstream: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[LogOut]:
    upstream_id: int | None = None
    if upstream is not None:
        u = await upstream_repo.get_by_name(upstream)
        if u is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"upstream '{upstream}' 不存在",
            )
        upstream_id = u.id

    rows = await log_repo.list_with_upstream(
        limit=limit,
        offset=offset,
        upstream_id=upstream_id,
        since=since,
        until=until,
    )
    return [
        LogOut(
            id=entry.id,
            created_at=entry.created_at,
            upstream=u.name if u is not None else None,
            model=entry.model,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            latency_ms=entry.latency_ms,
            status=entry.status,
            error=entry.error,
        )
        for entry, u in rows
    ]
