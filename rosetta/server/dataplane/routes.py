"""/v1/* 数据面路由(阶段 1.3:同格式直通,硬编第一个 enabled provider)。"""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider
from rosetta.server.database.session import get_session
from rosetta.server.dataplane.forwarder import forward
from rosetta.shared.formats import Format

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _pick_provider(session: AsyncSession) -> Provider:
    """阶段 1.3 硬编:取第一个 enabled provider;路由表要到阶段 3.1 才接入。"""
    result = await session.execute(
        select(Provider).where(Provider.enabled.is_(True)).order_by(Provider.id).limit(1)
    )
    provider = result.scalar_one_or_none()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="没有 enabled 的 provider,先 POST /admin/providers 建一个",
        )
    return provider


def _is_stream(body: bytes) -> bool:
    """从 JSON body 的 stream 字段判断;非 JSON 或无字段返 False。"""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(cast(dict[str, Any], data).get("stream", False))


@router.post("/v1/messages")
async def messages(request: Request, session: SessionDep) -> Response:
    body = await request.body()
    provider = await _pick_provider(session)
    return await forward(
        provider=provider,
        request_format=Format.MESSAGES,
        body=body,
        content_type=request.headers.get("content-type", "application/json"),
        is_stream=_is_stream(body),
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, session: SessionDep) -> Response:
    body = await request.body()
    provider = await _pick_provider(session)
    return await forward(
        provider=provider,
        request_format=Format.CHAT_COMPLETIONS,
        body=body,
        content_type=request.headers.get("content-type", "application/json"),
        is_stream=_is_stream(body),
    )


@router.post("/v1/responses")
async def responses_endpoint() -> Response:
    """v0.1 先不实现,阶段 2.5 再接入。"""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="/v1/responses 阶段 2.5 才实现",
    )
