"""/v1/* 数据面路由(阶段 1.3 → 2.x → 3.x)。

路径:
- `/v1/messages`:Messages 格式入口
- `/v1/chat/completions`:Chat Completions 入口
- `/v1/responses`:Responses 入口(2.5.1 起真翻译;跨格式时 forwarder 内部做 degrade)

阶段 3.1:upstream 选择从"第一个 enabled 硬编"换成 `pick_upstream`(DESIGN §8.4)。
阶段 3.2:客户端 `x-api-key` / `Authorization: Bearer` 透传给上游作 override。

分层约定:routes 是哑管道,只读 headers + 透传 body bytes。所有 body 解读
(model / stream 解析、Responses degrade、跨格式翻译)都在 forwarder 内部完成。
三端点结构对称,只差 `request_protocol` 参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.session import get_session
from rosetta.server.service.forwarder import forwarder
from rosetta.server.service.selector import pick_upstream
from rosetta.shared.protocols import Protocol

router = APIRouter()

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_client_api_key(request: Request) -> str | None:
    """按 DESIGN §8.1:客户端的 `x-api-key` 或 `Authorization: Bearer` 若提供,
    透传作为上游 key 的 override;两个都没给就返回 None,由 forwarder fallback 到
    `upstreams.api_key`。

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


@dataclass(frozen=True)
class RequestCtx:
    """dataplane 端点的请求门面:原始 body + 需要的 headers。

    body 是黑盒,routes 不解读;model / stream 等字段由 `pick_upstream` / `forwarder`
    内部按需解析。端点第一步 `ctx = await parse_request(request)`。
    """

    body: bytes
    rosetta_upstream: str | None
    content_type: str
    client_api_key: str | None


async def parse_request(request: Request) -> RequestCtx:
    """一次性读取 body + 需要的 headers,打包成 `RequestCtx`。"""
    return RequestCtx(
        body=await request.body(),
        rosetta_upstream=request.headers.get("x-rosetta-upstream"),
        content_type=request.headers.get("content-type", "application/json"),
        client_api_key=_extract_client_api_key(request),
    )


@router.post("/v1/messages")
async def messages(request: Request, session: SessionDep) -> Response:
    ctx = await parse_request(request)
    upstream = await pick_upstream(session, header_upstream=ctx.rosetta_upstream)
    return await forwarder.forward(
        upstream=upstream,
        request_protocol=Protocol.MESSAGES,
        body=ctx.body,
        content_type=ctx.content_type,
        client_api_key=ctx.client_api_key,
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, session: SessionDep) -> Response:
    ctx = await parse_request(request)
    upstream = await pick_upstream(session, header_upstream=ctx.rosetta_upstream)
    return await forwarder.forward(
        upstream=upstream,
        request_protocol=Protocol.CHAT_COMPLETIONS,
        body=ctx.body,
        content_type=ctx.content_type,
        client_api_key=ctx.client_api_key,
    )


@router.post("/v1/responses")
async def responses_endpoint(request: Request, session: SessionDep) -> Response:
    ctx = await parse_request(request)
    upstream = await pick_upstream(session, header_upstream=ctx.rosetta_upstream)
    return await forwarder.forward(
        upstream=upstream,
        request_protocol=Protocol.RESPONSES,
        body=ctx.body,
        content_type=ctx.content_type,
        client_api_key=ctx.client_api_key,
    )
