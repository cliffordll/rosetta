"""httpx 转发器 + SSE 流式透传 + 跨格式翻译接入(阶段 2.3-2.5)。

层次
----

1. `forward()`:dataplane 入口,接收客户端 format + body + provider + 流/非流标志
2. 按 `provider.type` 决定 upstream format;若与客户端 format 一致 → 走 `_forward_once`
   / `_forward_stream` 原样转发(兼容 1.3 路径,性能最优)
3. 否则走翻译路径:
   - 非流:`_forward_translated_once` → dispatcher.translate_request → 上游 → translate_response
   - 流:`_forward_translated_stream` → 上游 SSE → translate_stream_bytes → 客户端

httpx AsyncClient 由 app lifespan 管理(init_client / dispose_client)。
auth header 按 provider.type 分:anthropic 用 `x-api-key`,其余走 `Authorization: Bearer`。
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
from fastapi import HTTPException, status
from fastapi.responses import Response, StreamingResponse

from rosetta.server.database.models import Provider
from rosetta.server.translation.dispatcher import (
    translate_request,
    translate_response,
)
from rosetta.server.translation.stream import translate_stream_bytes
from rosetta.shared.formats import (
    DEFAULT_BASE_URL,
    UPSTREAM_PATH,
    Format,
    resolve_provider_format,
)

# 超时:连接 10s、读取 5min(LLM 长响应常态)
_DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)

_client: httpx.AsyncClient | None = None


async def init_client() -> None:
    global _client
    _client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)


async def dispose_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("httpx client 未初始化,先调 init_client()")
    return _client


def _base_url_for(provider: Provider) -> str:
    if provider.base_url:
        return provider.base_url.rstrip("/")
    default = DEFAULT_BASE_URL.get(provider.type)
    if not default:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"provider '{provider.name}' (type={provider.type}) 没配 base_url 且无默认值",
        )
    return default


def _auth_headers(provider: Provider, override_key: str | None = None) -> dict[str, str]:
    """按 `provider.type` 选上游鉴权头写法;`override_key` 非空则覆盖 DB 的 `api_key`。

    DESIGN §8.1 约定:客户端请求若带 `x-api-key` / `Authorization: Bearer`,
    server 把这把 key 透传给上游(**不做** rosetta-level 的鉴权),不带才 fallback
    到 `providers.api_key`。override 机制让"临时换一把 key 试试"不需要改 DB。
    """
    key = override_key or provider.api_key
    if provider.type == "anthropic":
        return {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
    return {"authorization": f"Bearer {key}"}


def _debug_log_upstream_key(headers: dict[str, str]) -> None:
    """TODO(阶段 3.2 验证通过后删):打印发给上游的 key 前 10 字符。

    用途:人肉验证"客户端带 key → 透传 / 不带 → DB fallback"两条分支的实际走向。
    本函数写到 stderr 而非 logger,等阶段 4 logger 落地后再决定是否保留到 debug 级别。
    """
    key = headers.get("x-api-key")
    if not key:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
    if key:
        print(f"[rosetta.debug] upstream key prefix = {key[:10]}...", file=sys.stderr)


async def forward(
    provider: Provider,
    request_format: Format,
    body: bytes,
    content_type: str,
    is_stream: bool,
    extra_response_headers: dict[str, str] | None = None,
    client_api_key: str | None = None,
) -> Response:
    """把请求按格式翻译(必要时)+ 转发到上游。

    `extra_response_headers`:由上层(例如 degradation 层)传入的附加响应头,
    例:`{"x-rosetta-warnings": "store_ignored,builtin_tools_removed:web_search"}`

    `client_api_key`:客户端通过 `x-api-key` / `Authorization: Bearer` 透传来的上游 key。
    为 None 时 forwarder 用 `provider.api_key`(DB 兜底)。见 DESIGN §8.1 / §8.5。
    """
    upstream_format = resolve_provider_format(provider.type)
    url = _base_url_for(provider) + UPSTREAM_PATH[upstream_format]
    headers = {
        "content-type": "application/json",
        **_auth_headers(provider, override_key=client_api_key),
    }
    _debug_log_upstream_key(headers)
    client = _get_client()

    # 同格式直通(阶段 1.3 路径)
    if upstream_format is request_format:
        if not is_stream:
            return _with_extra_headers(
                await _forward_once(client, url, headers, body),
                extra_response_headers,
            )
        return _with_extra_headers(
            await _forward_stream(client, url, headers, body),
            extra_response_headers,
        )

    # 跨格式翻译(阶段 2.3+)
    try:
        body_obj: Any = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"请求体不是合法 JSON: {e}",
        ) from e
    if not isinstance(body_obj, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请求体 JSON 顶层必须是对象",
        )

    try:
        _ir_req, upstream_body = translate_request(
            cast(dict[str, Any], body_obj), source=request_format, target=upstream_format
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"请求翻译失败({request_format.value} → {upstream_format.value}): {e}",
        ) from e

    upstream_bytes = json.dumps(upstream_body, ensure_ascii=False).encode("utf-8")

    if not is_stream:
        return _with_extra_headers(
            await _forward_translated_once(
                client,
                url,
                headers,
                upstream_bytes,
                upstream_format=upstream_format,
                client_format=request_format,
            ),
            extra_response_headers,
        )
    return _with_extra_headers(
        await _forward_translated_stream(
            client,
            url,
            headers,
            upstream_bytes,
            upstream_format=upstream_format,
            client_format=request_format,
        ),
        extra_response_headers,
    )


def _with_extra_headers(resp: Response, extra: dict[str, str] | None) -> Response:
    if extra:
        for k, v in extra.items():
            resp.headers[k] = v
    return resp


async def _forward_once(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: bytes,
) -> Response:
    try:
        resp = await client.post(url, headers=headers, content=body)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游不可达:{type(e).__name__}: {e}",
        ) from e
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )


async def _forward_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    body: bytes,
) -> Response:
    req = client.build_request("POST", url, headers=headers, content=body)
    try:
        upstream = await client.send(req, stream=True)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游不可达:{type(e).__name__}: {e}",
        ) from e

    if upstream.status_code >= 400:
        content = await upstream.aread()
        await upstream.aclose()
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    async def _iter() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        _iter(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "text/event-stream"),
    )


async def _forward_translated_once(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    upstream_body: bytes,
    *,
    upstream_format: Format,
    client_format: Format,
) -> Response:
    try:
        resp = await client.post(url, headers=headers, content=upstream_body)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游不可达:{type(e).__name__}: {e}",
        ) from e

    if resp.status_code >= 400:
        # 上游错误原样返回(不翻译),但保留客户端 format 语义:状态码 + body 透传
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    try:
        upstream_json: Any = resp.json()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游响应非 JSON: {e}",
        ) from e
    if not isinstance(upstream_json, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上游响应 JSON 顶层必须是对象",
        )

    try:
        _ir_resp, client_body = translate_response(
            cast(dict[str, Any], upstream_json), source=upstream_format, target=client_format
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"响应翻译失败({upstream_format.value} → {client_format.value}): {e}",
        ) from e

    return Response(
        content=json.dumps(client_body, ensure_ascii=False).encode("utf-8"),
        status_code=resp.status_code,
        media_type="application/json",
    )


async def _forward_translated_stream(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    upstream_body: bytes,
    *,
    upstream_format: Format,
    client_format: Format,
) -> Response:
    """流式翻译:上游 SSE → `translate_stream_bytes` → 客户端 SSE。

    错误传播(DESIGN §8.3):
    - 上游非 2xx(未进入流)→ 原样透传错误响应
    - 上游 2xx 但流中抛异常 → 生成器 raise,StreamingResponse 关闭连接
      (不向客户端伪造额外事件)
    """
    req = client.build_request("POST", url, headers=headers, content=upstream_body)
    try:
        upstream = await client.send(req, stream=True)
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"上游不可达:{type(e).__name__}: {e}",
        ) from e

    if upstream.status_code >= 400:
        content = await upstream.aread()
        await upstream.aclose()
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    async def _iter_upstream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    async def _iter_translated() -> AsyncIterator[bytes]:
        async for out in translate_stream_bytes(
            _iter_upstream(),
            source=upstream_format,
            target=client_format,
        ):
            yield out

    return StreamingResponse(
        _iter_translated(),
        status_code=upstream.status_code,
        media_type="text/event-stream",
    )
