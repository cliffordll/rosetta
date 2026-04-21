"""httpx 转发器 + SSE 流式透传。

阶段 1.3:同格式直通,不做翻译。阶段 2 起 dispatcher 介入。

- 全局 `httpx.AsyncClient` 由 app lifespan 管理(init_client / dispose_client)
- `forward()` 根据 is_stream 分派到一次性 / 流式两条路径
- auth header 按 provider.type 选:anthropic 用 `x-api-key`,其余走 `Authorization: Bearer`
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from fastapi import HTTPException, status
from fastapi.responses import Response, StreamingResponse

from rosetta.server.database.models import Provider
from rosetta.shared.formats import DEFAULT_BASE_URL, UPSTREAM_PATH, Format

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
    """provider.base_url 非空用它;否则按 type 取 DEFAULT_BASE_URL;custom 无默认会在此报错。"""
    if provider.base_url:
        return provider.base_url.rstrip("/")
    default = DEFAULT_BASE_URL.get(provider.type)
    if not default:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"provider '{provider.name}' (type={provider.type}) 没配 base_url 且无默认值",
        )
    return default


def _auth_headers(provider: Provider) -> dict[str, str]:
    """按上游 type 选 auth header 名称。

    阶段 1.3 一律用 provider.api_key;客户端侧的 `x-api-key` 透传规则放到阶段 3.2。
    """
    if provider.type == "anthropic":
        return {
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        }
    # openai / openrouter / custom 走 OpenAI 风格的 Bearer
    return {"authorization": f"Bearer {provider.api_key}"}


async def forward(
    provider: Provider,
    request_format: Format,
    body: bytes,
    content_type: str,
    is_stream: bool,
) -> Response:
    """把请求原样转到上游,返回 FastAPI Response(流式用 StreamingResponse)。"""
    url = _base_url_for(provider) + UPSTREAM_PATH[request_format]
    headers = {"content-type": content_type, **_auth_headers(provider)}
    client = _get_client()

    if not is_stream:
        return await _forward_once(client, url, headers, body)
    return await _forward_stream(client, url, headers, body)


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
    """流式透传。

    用 `send(stream=True)` 先拿到状态码;非 2xx 读完 body 转成非流式错误响应;
    2xx 包 `StreamingResponse` 逐 chunk 吐,保持连接直到生成器退出时才 aclose。
    """
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
