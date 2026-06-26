"""/v1/* 数据面路由(阶段 1.3 → 2.x → 3.x)。

路径:
- `/v1/messages`:Messages 格式入口
- `/v1/chat/completions`:Chat Completions 入口
- `/v1/responses`:Responses 入口(2.5.1 起真翻译;跨格式时 forwarder 内部做 degrade)
- `/responses`:兼容旧 Codex Rosetta 配置,等同 `/v1/responses`

阶段 3.1:upstream 选择从"第一个 enabled 硬编"换成 `pick_upstream`(DESIGN §8.4)。
阶段 3.2:客户端按入口协议传的真实鉴权头作为上游 key override。

分层约定:routes 是哑管道,只读 headers + 透传 body bytes。所有 body 解读
(model / stream 解析、Responses degrade、跨格式翻译)都在 forwarder 内部完成。
三端点结构对称,只差 `server_api` 参数。
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
from rosetta.server.service.selector import select_upstream, setup_scope_for_server_api
from rosetta.shared.server_api import ServerApi

router = APIRouter()


def _extract_client_api_key(request: Request, server_api: ServerApi) -> str | None:
    """提取客户端按入口协议带来的真实 API key,作为上游 key override。

    优先级:
    - `ServerApi.MESSAGES`(Claude): 取 `x-api-key`。
    - 其他(OpenAI-compatible): 取 `Authorization: Bearer <token>` 中的 token。

    `Authorization` 在 OpenAI-compatible 客户端里就是真实上游 key(Codex CLI 等);`
    `r-api-key` 仅用于 Rosetta server-level 鉴权(暂不启用),不参与上游 override。
    """
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
    rewrite_model_to_upstream: bool = False


@dataclass(frozen=True)
class RequestCtx:
    """dataplane 端点的请求门面:原始 body + 需要的 headers + 客户端地址。

    body 是黑盒,routes 不解读;model / stream 等字段由 `pick_upstream` / `forwarder`
    内部按需解析。端点第一步 `ctx = await parse_request(request, server_api)`。
    """

    body: bytes
    rosetta_upstream: str | None
    content_type: str
    client_api_key: str | None
    client_addr: str | None
    model: str | None
    server_api: ServerApi


def _extract_client_addr(request: Request) -> str | None:
    """FastAPI request.client 的 'host:port' 字符串;ASGI / HTTP/2 / 反代下可能是 None。"""
    client = request.client
    if client is None:
        return None
    return f"{client.host}:{client.port}"


async def parse_request(request: Request, server_api: ServerApi) -> RequestCtx:
    """一次性读取 body + 需要的 headers,打包成 `RequestCtx`。"""
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
    """短生命周期读取数据面配置,避免 DB session 跨越流式转发阶段。"""
    session_maker = get_session_maker()
    if session_maker is None:
        raise RuntimeError("DB 未初始化,先调 init_db()")
    session = session_maker()
    try:
        selection = await select_upstream(
            session,
            header_upstream=ctx.rosetta_upstream,
            model=ctx.model,
            setup_scope=setup_scope_for_server_api(ctx.server_api),
        )
        upstream = selection.upstream
        rewrite_model_to_upstream = selection.rewrite_model_to_upstream
        await session.commit()
    finally:
        await close_session_safely(session)
    return DataplaneConfig(upstream, rewrite_model_to_upstream=rewrite_model_to_upstream)


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
        rewrite_model_to_upstream=config.rewrite_model_to_upstream,
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
        rewrite_model_to_upstream=config.rewrite_model_to_upstream,
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
        rewrite_model_to_upstream=config.rewrite_model_to_upstream,
    )
