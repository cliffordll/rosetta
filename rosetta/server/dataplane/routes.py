"""/v1/* 数据面路由(阶段 1.3 → 2.x → 3.x)。

路径:
- `/v1/messages`:Messages 格式入口
- `/v1/chat/completions`:Chat Completions 入口
- `/v1/responses`:Responses 入口(2.5.1 起真翻译;2.5.2 走 degradation 预处理)

阶段 3.1:provider 选择从"第一个 enabled 硬编"换成 `pick_provider`(DESIGN §8.4)。
阶段 3.2:客户端 `x-api-key` / `Authorization: Bearer` 透传给上游作 override。
"""

from __future__ import annotations

import json
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.session import get_session
from rosetta.server.dataplane.forwarder import forward
from rosetta.server.dataplane.router import parse_model, pick_provider
from rosetta.server.translation.degradation import (
    StatefulNotTranslatableError,
    degrade_responses_request,
)
from rosetta.shared.formats import Format, resolve_provider_format

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _is_stream(body: bytes) -> bool:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(cast(dict[str, Any], data).get("stream", False))


def _extract_client_api_key(request: Request) -> str | None:
    """按 DESIGN §8.1:客户端的 `x-api-key` 或 `Authorization: Bearer` 若提供,
    透传作为上游 key 的 override;两个都没给就返回 None,由 forwarder fallback 到
    `providers.api_key`。

    同时存在时优先取 `x-api-key`(Anthropic 风格,显式度高于 Authorization)。
    """
    xapikey = request.headers.get("x-api-key")
    if xapikey:
        return xapikey
    auth = request.headers.get("authorization")
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            if token:
                return token
    return None


@router.post("/v1/messages")
async def messages(request: Request, session: SessionDep) -> Response:
    body = await request.body()
    provider = await pick_provider(
        session,
        model=parse_model(body),
        header_provider=request.headers.get("x-rosetta-provider"),
    )
    return await forward(
        provider=provider,
        request_format=Format.MESSAGES,
        body=body,
        content_type=request.headers.get("content-type", "application/json"),
        is_stream=_is_stream(body),
        client_api_key=_extract_client_api_key(request),
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, session: SessionDep) -> Response:
    body = await request.body()
    provider = await pick_provider(
        session,
        model=parse_model(body),
        header_provider=request.headers.get("x-rosetta-provider"),
    )
    return await forward(
        provider=provider,
        request_format=Format.CHAT_COMPLETIONS,
        body=body,
        content_type=request.headers.get("content-type", "application/json"),
        is_stream=_is_stream(body),
        client_api_key=_extract_client_api_key(request),
    )


@router.post("/v1/responses")
async def responses_endpoint(request: Request, session: SessionDep) -> Response:
    """Responses API 入口(2.5.1 / 2.5.2)。

    与另两条路径的差异:需要先走 `degrade_responses_request` 处理有状态字段 + 内置 tools,
    再送入翻译链。降级产生的 warnings 通过 `x-rosetta-warnings` 响应头返回客户端。
    """
    raw = await request.body()
    provider = await pick_provider(
        session,
        model=parse_model(raw),
        header_provider=request.headers.get("x-rosetta-provider"),
    )
    target_format = resolve_provider_format(provider.type)

    try:
        raw_json: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"请求体不是合法 JSON: {e}",
        ) from e
    if not isinstance(raw_json, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请求体 JSON 顶层必须是对象",
        )

    try:
        degraded = degrade_responses_request(
            cast(dict[str, Any], raw_json), target_format=target_format
        )
    except StatefulNotTranslatableError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "stateful_not_translatable",
                    "message": str(e),
                    "field": e.field_name,
                }
            },
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Responses 请求降级失败: {e}",
        ) from e

    body = json.dumps(degraded.body, ensure_ascii=False).encode("utf-8")
    warnings_header = degraded.warnings_header()
    extra_headers: dict[str, str] | None = (
        {"x-rosetta-warnings": warnings_header} if warnings_header else None
    )

    return await forward(
        provider=provider,
        request_format=Format.RESPONSES,
        body=body,
        content_type=request.headers.get("content-type", "application/json"),
        is_stream=_is_stream(body),
        extra_response_headers=extra_headers,
        client_api_key=_extract_client_api_key(request),
    )
