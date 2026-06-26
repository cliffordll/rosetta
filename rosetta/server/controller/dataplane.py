"""/v1/* 数据面路由(阶段 1.3 → 2.x → 3.x)。

路径:
- `/v1/messages`:Messages 格式入口
- `/v1/chat/completions`:Chat Completions 入口
- `/v1/responses`:Responses 入口(2.5.1 起真翻译;跨格式时 forwarder 内部做 degrade)
- `/responses`:兼容旧 Codex Rosetta 配置,等同 `/v1/responses`

路由:models JOIN upstream_models JOIN upstreams 选取 enabled upstream。
rewrite_model_to 不为 NULL 时 forwarder 替换 body.model。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import Response

from rosetta.server.database.models import Upstream
from rosetta.server.database.session import close_session_safely, get_session_maker
from rosetta.server.service.forwarder import forwarder
from rosetta.server.service.selector import select_upstream
from rosetta.shared.server_api import ServerApi

router = APIRouter()


def _extract_client_api_key(request: Request, server_api: ServerApi) -> str | None:
    if server_api == ServerApi.MESSAGES:
        return request.headers.get("x-api-key")
    auth = request.headers.get("authorization", "")
    prefix = "Bearer "
    if auth.startswith(prefix):
        return auth[len(prefix) :].strip()
    return None


@dataclass(frozen=True)
class DataplaneConfig:
    upstream: Upstream
    alias: str | None = None
    rewrite_model_to: str | None = None


@dataclass(frozen=True)
class RequestCtx:
    body: bytes
    rosetta_upstream: str | None
    content_type: str
    client_api_key: str | None
    client_addr: str | None
    model: str | None
    server_api: ServerApi


def _extract_client_addr(request: Request) -> str | None:
    client = request.client
    if client is None:
        return None
    return f"{client.host}:{client.port}"


async def parse_request(request: Request, server_api: ServerApi) -> RequestCtx:
    body = await request.body()
    return RequestCtx(
        body=body,
        rosetta_upstream=request.headers.get("r-upstream"),
        content_type=request.headers.get("content-type", "application/json"),
        client_api_key=_extract_client_api_key(request, server_api),
        client_addr=_extract_client_addr(request),
        model=_model_from_body(body),
        server_api=server_api,
    )


def _model_from_body(body: bytes) -> str | None:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    model = cast(dict[str, Any], data).get("model")
    if not isinstance(model, str) or not model.strip():
        return None
    return model


async def load_dataplane_config(ctx: RequestCtx) -> DataplaneConfig:
    session_maker = get_session_maker()
    if session_maker is None:
        raise RuntimeError("DB 未初始化,先调 init_db()")
    session = session_maker()
    try:
        selection = await select_upstream(
            session,
            header_upstream=ctx.rosetta_upstream,
            model=ctx.model,
        )
        await session.commit()
    finally:
        await close_session_safely(session)
    return DataplaneConfig(
        selection.upstream,
        alias=selection.alias,
        rewrite_model_to=selection.rewrite_model_to,
    )


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    server_api = ServerApi.MESSAGES
    ctx = await parse_request(request, server_api)
    config = await load_dataplane_config(ctx)
    return await forwarder.forward(
        upstream=config.upstream,
        server_api=server_api,
        body=ctx.body,
        content_type=ctx.content_type,
        client_api_key=ctx.client_api_key,
        client_addr=ctx.client_addr,
        alias=config.alias,
        rewrite_model_to=config.rewrite_model_to,
    )


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    server_api = ServerApi.CHAT_COMPLETIONS
    ctx = await parse_request(request, server_api)
    config = await load_dataplane_config(ctx)
    return await forwarder.forward(
        upstream=config.upstream,
        server_api=server_api,
        body=ctx.body,
        content_type=ctx.content_type,
        client_api_key=ctx.client_api_key,
        client_addr=ctx.client_addr,
        alias=config.alias,
        rewrite_model_to=config.rewrite_model_to,
    )


@router.post("/responses")
@router.post("/v1/responses")
async def responses_endpoint(request: Request) -> Response:
    server_api = ServerApi.RESPONSES
    ctx = await parse_request(request, server_api)
    config = await load_dataplane_config(ctx)
    return await forwarder.forward(
        upstream=config.upstream,
        server_api=server_api,
        body=ctx.body,
        content_type=ctx.content_type,
        client_api_key=ctx.client_api_key,
        client_addr=ctx.client_addr,
        alias=config.alias,
        rewrite_model_to=config.rewrite_model_to,
    )
