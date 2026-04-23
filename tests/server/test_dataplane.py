"""数据面 forwarder 测试(阶段 1.3 / 2.3 / 3.2)。

用 `httpx.MockTransport` 直接拦截 httpx 请求,不启真实 HTTP server;
覆盖:
- 同格式直通(messages/completions/responses)的 URL 组装 + header
- upstream.protocol=messages:鉴权头用 `x-api-key` + `anthropic-version`
- upstream.protocol=completions / responses:`Authorization: Bearer`
- client_api_key 透传 vs upstream.api_key 兜底
- 跨格式翻译(messages → completions)的请求 / 响应都被翻译
- extra_response_headers(x-rosetta-warnings)注入响应
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio

from rosetta.server.database.models import Upstream
from rosetta.server.service.forwarder import forwarder
from rosetta.shared.protocols import Protocol

RequestHandler = Callable[[httpx.Request], httpx.Response]


@pytest_asyncio.fixture
async def mock_client() -> AsyncIterator[dict[str, Any]]:
    """暴露一个 captured dict:测试里 set `captured["handler"]` 定义响应,
    每次 handler 被调都会把最后一次 request 写到 `captured["request"]`。

    fixture 把模块级 `forwarder` 的 httpx client monkey-patch 成 mock transport,
    teardown 时 reset 回 None,保证测试间不串 state。
    """
    captured: dict[str, Any] = {"request": None, "handler": None}

    def _dispatch(req: httpx.Request) -> httpx.Response:
        captured["request"] = req
        h = captured.get("handler")
        if h is None:
            return httpx.Response(200, json={})
        return h(req)  # type: ignore[no-any-return]

    transport = httpx.MockTransport(_dispatch)
    client = httpx.AsyncClient(transport=transport)
    forwarder._client = client
    try:
        yield captured
    finally:
        await client.aclose()
        forwarder._client = None


def _anthropic_upstream(**overrides: Any) -> Upstream:
    base = {
        "id": "ant-fixed-id",
        "name": "ant",
        "protocol": "messages",
        "provider": "anthropic",
        "api_key": "sk-ant-dbkey",
        "base_url": "https://api.anthropic.com",
        "enabled": True,
    }
    base.update(overrides)
    return Upstream(**base)


def _openai_upstream(**overrides: Any) -> Upstream:
    base = {
        "id": "oai-fixed-id",
        "name": "oai",
        "protocol": "completions",
        "provider": "openai",
        "api_key": "sk-oai-dbkey",
        "base_url": "https://api.openai.com",
        "enabled": True,
    }
    base.update(overrides)
    return Upstream(**base)


# ---------- 同格式直通 ----------


async def test_anthropic_passthrough_url_and_headers(
    mock_client: dict[str, Any],
) -> None:
    mock_client["handler"] = lambda req: httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-haiku-4-5",
            "content": [{"type": "text", "text": "hi"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 2},
        },
    )

    body = json.dumps({"model": "claude-haiku-4-5", "messages": []}).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_anthropic_upstream(),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200

    req = mock_client["request"]
    assert req.url.path == "/v1/messages"
    assert str(req.url).startswith("https://api.anthropic.com")
    assert req.headers["x-api-key"] == "sk-ant-dbkey"
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in req.headers


async def test_openai_passthrough_url_and_headers(
    mock_client: dict[str, Any],
) -> None:
    mock_client["handler"] = lambda req: httpx.Response(
        200,
        json={
            "id": "chatcmpl_1",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
    )

    body = json.dumps({"model": "gpt-4o-mini", "messages": []}).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_openai_upstream(),
        request_protocol=Protocol.CHAT_COMPLETIONS,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200

    req = mock_client["request"]
    assert req.url.path == "/v1/chat/completions"
    assert str(req.url).startswith("https://api.openai.com")
    assert req.headers["authorization"] == "Bearer sk-oai-dbkey"
    assert "x-api-key" not in req.headers


# ---------- api-key 覆盖 vs 兜底 ----------


async def test_client_api_key_overrides_db(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(api_key="sk-DB-value"),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
        client_api_key="sk-CLIENT-override",
    )
    req = mock_client["request"]
    assert req.headers["x-api-key"] == "sk-CLIENT-override"


async def test_client_none_falls_back_to_db(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "gpt-4o-mini"}).encode("utf-8")
    await forwarder.forward(
        upstream=_openai_upstream(api_key="sk-DB-bearer"),
        request_protocol=Protocol.CHAT_COMPLETIONS,
        body=body,
        content_type="application/json",
        client_api_key=None,
    )
    req = mock_client["request"]
    assert req.headers["authorization"] == "Bearer sk-DB-bearer"


# ---------- 自定义 base_url ----------


async def test_custom_base_url_used(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(base_url="http://127.0.0.1:8765/"),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
    )
    req = mock_client["request"]
    # 尾部 / 被 rstrip,上游路径拼到 base_url 末尾
    assert str(req.url) == "http://127.0.0.1:8765/v1/messages"


# ---------- 跨格式翻译 ----------


async def test_cross_format_messages_to_completions(
    mock_client: dict[str, Any],
) -> None:
    """messages 请求 + completions upstream → 请求翻成 completions,响应再翻回 messages。"""

    # 上游按 completions 方言响应(因为 upstream.protocol=completions)
    def _upstream(req: httpx.Request) -> httpx.Response:
        # 确认发上去的是 completions 形状
        body = json.loads(req.content)
        assert body["model"] == "gpt-4o-mini"
        assert "messages" in body
        # 必须有 "max_tokens"(IR → completions dump 出的字段)
        assert "max_tokens" in body
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_x",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "yes"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            },
        )

    mock_client["handler"] = _upstream

    client_body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "max_tokens": 64,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]}
            ],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_openai_upstream(),
        request_protocol=Protocol.MESSAGES,  # 客户端发的是 messages 格式
        body=client_body,
        content_type="application/json",
    )
    assert resp.status_code == 200
    # 返给客户端的是 messages 格式(type=message,content 数组)
    response_body = json.loads(resp.body)
    assert response_body["type"] == "message"
    assert response_body["role"] == "assistant"
    assert any(
        b.get("type") == "text" and b.get("text") == "yes"
        for b in response_body["content"]
    )


# ---------- extra_response_headers ----------


async def test_extra_response_headers_injected(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_anthropic_upstream(),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
        extra_response_headers={"x-rosetta-warnings": "store_ignored"},
    )
    assert resp.headers.get("x-rosetta-warnings") == "store_ignored"


# ---------- 未初始化 client 的防御 ----------


async def test_forward_without_open_raises() -> None:
    """模块级 forwarder 未 open(mock_client fixture 没注入)时,必须抛明确错误而不是默许 None。"""
    assert forwarder._client is None
    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    with pytest.raises(RuntimeError, match="httpx client 未初始化"):
        await forwarder.forward(
            upstream=_anthropic_upstream(),
            request_protocol=Protocol.MESSAGES,
            body=body,
            content_type="application/json",
            )
