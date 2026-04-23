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


# ---------- provider=mock 短路 ----------


def _mock_upstream() -> Upstream:
    return Upstream(
        id="m" * 32,
        name="mock",
        protocol="any",  # mock 不发 HTTP,protocol 语义不适用
        provider="mock",
        api_key=None,
        base_url="mock://",
        enabled=True,
    )


async def _drain_stream(resp: Any) -> bytes:
    """StreamingResponse.body_iterator 收完整流;mock 路径不打网络,瞬时返回。"""
    buf = bytearray()
    async for chunk in resp.body_iterator:
        buf.extend(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
    return bytes(buf)


def _sse_data_payloads(raw: str) -> list[dict[str, Any]]:
    """把 SSE 原始字节 decode 后按 `\\n\\n` 切帧,抽出每帧的 `data:` JSON。"""
    payloads: list[dict[str, Any]] = []
    for frame in raw.split("\n\n"):
        data_lines = [
            line[len("data:"):].lstrip()
            for line in frame.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        data_str = "\n".join(data_lines)
        if data_str.strip() == "[DONE]":
            continue
        try:
            parsed = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payloads.append(parsed)
    return payloads


def _concat_messages_text(raw: str) -> str:
    """messages SSE:拼 `content_block_delta.delta.text`。"""
    out = ""
    for data in _sse_data_payloads(raw):
        if data.get("type") == "content_block_delta":
            delta = data.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str):
                    out += text
    return out


def _concat_completions_text(raw: str) -> str:
    """completions SSE:拼 `choices[0].delta.content`。"""
    out = ""
    for data in _sse_data_payloads(raw):
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = choices[0]
        if not isinstance(first, dict):
            continue
        delta = first.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                out += content
    return out


def _concat_responses_text(raw: str) -> str:
    """responses SSE:拼 `response.output_text.delta.delta`。"""
    out = ""
    for data in _sse_data_payloads(raw):
        if data.get("type") == "response.output_text.delta":
            delta = data.get("delta")
            if isinstance(delta, str):
                out += delta
    return out


async def test_mock_provider_messages_stream_echoes_user_text() -> None:
    """provider=mock + messages 流式:短路不发 HTTP,SSE 含 text_delta + message_delta usage。"""
    body = json.dumps(
        {
            "model": "claude-haiku-4-5",
            "max_tokens": 128,
            "stream": True,
            "messages": [{"role": "user", "content": "hello mock"}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_mock_upstream(),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"

    raw = (await _drain_stream(resp)).decode("utf-8")
    assert "event: message_start" in raw
    assert "content_block_delta" in raw
    assert "message_delta" in raw
    assert "message_stop" in raw
    # 拼回文本后断言 echo 前缀(含 protocol)+ 用户输入
    reply = _concat_messages_text(raw)
    assert reply.startswith("[mock:messages] echo:")
    assert "hello mock" in reply


async def test_mock_provider_completions_stream_has_usage_chunk() -> None:
    """provider=mock + completions 流式:末尾含单独 usage chunk + data: [DONE]。"""
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "hi there"}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_mock_upstream(),
        request_protocol=Protocol.CHAT_COMPLETIONS,
        body=body,
        content_type="application/json",
    )
    raw = (await _drain_stream(resp)).decode("utf-8")
    reply = _concat_completions_text(raw)
    assert reply.startswith("[mock:completions] echo:")
    assert "hi there" in reply
    assert '"finish_reason": "stop"' in raw
    assert '"prompt_tokens"' in raw and '"completion_tokens"' in raw
    assert raw.rstrip().endswith("data: [DONE]")


async def test_mock_provider_responses_stream_has_completed_usage() -> None:
    """provider=mock + responses 流式:`response.output_text.delta` + `response.completed.usage`。"""
    body = json.dumps(
        {
            "model": "gpt-4o-mini",
            "stream": True,
            "max_output_tokens": 64,
            "input": [{"type": "message", "role": "user", "content": "ping"}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_mock_upstream(),
        request_protocol=Protocol.RESPONSES,
        body=body,
        content_type="application/json",
    )
    raw = (await _drain_stream(resp)).decode("utf-8")
    assert "response.output_text.delta" in raw
    assert "response.completed" in raw
    assert '"input_tokens"' in raw and '"output_tokens"' in raw
    reply = _concat_responses_text(raw)
    assert reply.startswith("[mock:responses] echo:")
    assert "ping" in reply


async def test_mock_provider_messages_non_stream_returns_json() -> None:
    """非流模式返回一个完整 messages JSON;usage + echo 文本都在。"""
    body = json.dumps(
        {
            "model": "claude-haiku-4-5",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "hola"}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_mock_upstream(),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.media_type == "application/json"
    data = json.loads(bytes(resp.body))
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"][0]["text"].endswith("hola")
    assert data["content"][0]["text"].startswith("[mock:messages] echo:")
    assert data["usage"]["input_tokens"] >= 1
    assert data["usage"]["output_tokens"] >= 1


async def test_mock_provider_bypasses_httpx_client() -> None:
    """forwarder 未 open(no mock transport)时 mock 分支仍能工作——证明没打 HTTP。"""
    assert forwarder._client is None
    body = json.dumps({"model": "x", "max_tokens": 16, "messages": []}).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_mock_upstream(),
        request_protocol=Protocol.MESSAGES,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200
