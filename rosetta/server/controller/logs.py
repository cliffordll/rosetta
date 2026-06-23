"""/admin/logs:请求流水列表查询(阶段 4.2)。

v0.1 没 logger 真往 logs 表写入,因此本端点常态返空。保留是为让 CLI / GUI 的
"logs 列表"有统一接入点;等后续 logger 组件接入后直接生效。

查询参数:
- `limit`(默认 50,上限 500)
- `offset`(默认 0)
- `upstream`:按 upstream name 过滤(server 内部 JOIN 到 id)
- `since` / `until`:ISO 8601 时间戳过滤 `created_at`

响应:`{items: LogOut[], total: int}` — `total` 是同条件下的全表计数(用于分页器
渲染 totalPages),不受 `limit`/`offset` 影响。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from rosetta.server.logs_config import LogContentMode, LogsPageSize
from rosetta.server.repository import LogRepoDep, SettingsRepoDep, UpstreamRepoDep

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
    client_addr: str | None
    upstream_url: str | None
    request_text: str | None
    response_text: str | None


class LogListResponse(BaseModel):
    items: list[LogOut]
    total: int


class LogsConfigOut(BaseModel):
    log_content: LogContentMode
    page_size: LogsPageSize


class LogsConfigUpdate(BaseModel):
    log_content: LogContentMode | None = None
    page_size: LogsPageSize | None = None


class LogsClearOut(BaseModel):
    deleted: int


@router.get("/logs/config", response_model=LogsConfigOut)
async def get_logs_config(settings_repo: SettingsRepoDep) -> LogsConfigOut:
    config = await settings_repo.get_logs_config()
    return LogsConfigOut(log_content=config.log_content, page_size=config.page_size)


@router.put("/logs/config", response_model=LogsConfigOut)
async def update_logs_config(
    payload: LogsConfigUpdate,
    settings_repo: SettingsRepoDep,
) -> LogsConfigOut:
    if payload.log_content is None and payload.page_size is None:
        config = await settings_repo.get_logs_config()
        return LogsConfigOut(log_content=config.log_content, page_size=config.page_size)
    config = await settings_repo.update_logs_config(
        log_content=payload.log_content,
        page_size=payload.page_size,
    )
    return LogsConfigOut(log_content=config.log_content, page_size=config.page_size)


@router.get("/logs", response_model=LogListResponse)
async def list_logs(
    log_repo: LogRepoDep,
    upstream_repo: UpstreamRepoDep,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    upstream: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> LogListResponse:
    upstream_id: str | None = None
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
    total = await log_repo.count_with_filters(
        upstream_id=upstream_id,
        since=since,
        until=until,
    )
    items = [
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
            client_addr=entry.client_addr,
            upstream_url=entry.upstream_url,
            request_text=entry.request_text,
            response_text=entry.response_text,
        )
        for entry, u in rows
    ]
    return LogListResponse(items=items, total=total)


@router.delete("/logs", response_model=LogsClearOut)
async def clear_logs(log_repo: LogRepoDep) -> LogsClearOut:
    deleted = await log_repo.clear()
    return LogsClearOut(deleted=deleted)
