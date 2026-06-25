"""数据面 forwarder 测试(阶段 1.3 / 2.3 / 3.2)。

用 `httpx.MockTransport` 直接拦截 httpx 请求,不启真实 HTTP server;
覆盖:
- 同格式直通(messages/completions/responses)的 URL 组装 + header
- upstream.native_api=messages:鉴权头用 `x-api-key` + `anthropic-version`
- upstream.native_api=completions / responses:`Authorization: Bearer`
- client_api_key 透传 vs upstream.api_key 兜底
- 跨格式翻译(messages → completions)的请求 / 响应都被翻译
- extra_response_headers(r-warnings)注入响应
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.controller import dataplane_router
from rosetta.server.controller.dataplane import _extract_client_api_key, parse_request
from rosetta.server.database.models import LogEntry, Upstream
from rosetta.server.database.session import get_session
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.forwarder import forwarder
from rosetta.shared.server_api import ServerApi

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
        "native_api": "messages",
        "provider": "anthropic",
        "api_key": "sk-ant-dbkey",
        "base_url": "https://api.anthropic.com",
        "model": None,
        "enabled": True,
    }
    base.update(overrides)
    return Upstream(**base)


def _openai_upstream(**overrides: Any) -> Upstream:
    base = {
        "id": "oai-fixed-id",
        "name": "oai",
        "native_api": "completions",
        "provider": "openai",
        "api_key": "sk-oai-dbkey",
        "base_url": "https://api.openai.com",
        "model": None,
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
        server_api=ServerApi.MESSAGES,
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


async def test_forwarder_allows_base_url_with_path_prefix(
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
        upstream=_anthropic_upstream(base_url="https://gateway.example.com/proxy/ant/"),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert str(mock_client["request"].url) == "https://gateway.example.com/proxy/ant/v1/messages"


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
        server_api=ServerApi.CHAT_COMPLETIONS,
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


def test_authorization_header_is_upstream_key_override_for_completions() -> None:
    request = SimpleNamespace(headers={"authorization": "Bearer codex-local-token"})

    assert _extract_client_api_key(request, ServerApi.CHAT_COMPLETIONS) == "codex-local-token"
    assert _extract_client_api_key(request, ServerApi.RESPONSES) == "codex-local-token"


def test_authorization_header_is_not_extracted_for_messages() -> None:
    request = SimpleNamespace(headers={"authorization": "Bearer codex-local-token"})

    assert _extract_client_api_key(request, ServerApi.MESSAGES) is None  # type: ignore[arg-type]


def test_x_api_key_header_is_upstream_key_override_for_messages() -> None:
    request = SimpleNamespace(headers={"x-api-key": "sk-ant-client"})

    assert _extract_client_api_key(request, ServerApi.MESSAGES) == "sk-ant-client"


def test_x_api_key_header_is_not_extracted_for_completions() -> None:
    request = SimpleNamespace(headers={"x-api-key": "sk-ant-client"})

    assert _extract_client_api_key(request, ServerApi.CHAT_COMPLETIONS) is None  # type: ignore[arg-type]


def test_r_api_key_is_not_upstream_key_override() -> None:
    request = SimpleNamespace(headers={"r-api-key": "sk-CLIENT-override"})

    assert _extract_client_api_key(request, ServerApi.CHAT_COMPLETIONS) is None  # type: ignore[arg-type]
    assert _extract_client_api_key(request, ServerApi.MESSAGES) is None  # type: ignore[arg-type]


async def test_parse_request_uses_endpoint_server_api_for_client_key() -> None:
    async def _body() -> bytes:
        return b'{"model":"claude-haiku-4-5"}'

    request = SimpleNamespace(
        body=_body,
        headers={"content-type": "application/json", "x-api-key": "sk-ant-client"},
        client=SimpleNamespace(host="127.0.0.1", port=12345),
    )

    ctx = await parse_request(request, ServerApi.MESSAGES)  # type: ignore[arg-type]

    assert ctx.client_api_key == "sk-ant-client"
    assert ctx.model == "claude-haiku-4-5"


async def test_dataplane_route_does_not_use_fastapi_session_dependency(
    session: AsyncSession,
) -> None:
    repo = UpstreamRepo(session)
    mock = await repo.get_by_name("mock")
    assert mock is not None
    await repo.update(mock.id, model="claude-haiku-4-5")

    app = FastAPI()
    app.include_router(dataplane_router)

    async def _unexpected_session_dependency() -> AsyncIterator[AsyncSession]:
        yield session
        raise AssertionError("dataplane should not hold FastAPI DB dependency")

    app.dependency_overrides[get_session] = _unexpected_session_dependency

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            "/v1/messages",
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    assert response.status_code == 200


async def test_client_api_key_overrides_db(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(api_key="sk-DB-value"),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
        client_api_key="sk-CLIENT-override",
    )
    req = mock_client["request"]
    assert req.headers["x-api-key"] == "sk-CLIENT-override"


async def test_client_api_key_override_does_not_log_key_prefix(
    mock_client: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """透传客户端 key 时不应向 stderr 打印 key 前缀。"""
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(api_key="sk-DB-value"),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
        client_api_key="sk-CLIENT-override",
    )

    captured = capsys.readouterr()
    assert "rosetta.debug" not in captured.err
    assert "sk-CLIENT" not in captured.err


async def test_client_none_falls_back_to_db(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "gpt-4o-mini"}).encode("utf-8")
    await forwarder.forward(
        upstream=_openai_upstream(api_key="sk-DB-bearer"),
        server_api=ServerApi.CHAT_COMPLETIONS,
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
        server_api=ServerApi.MESSAGES,
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

    # 上游按 completions 方言响应(因为 upstream.native_api=completions)
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
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_openai_upstream(),
        server_api=ServerApi.MESSAGES,  # 客户端发的是 messages 格式
        body=client_body,
        content_type="application/json",
    )
    assert resp.status_code == 200
    # 返给客户端的是 messages 格式(type=message,content 数组)
    response_body = json.loads(resp.body)
    assert response_body["type"] == "message"
    assert response_body["role"] == "assistant"
    assert any(b.get("type") == "text" and b.get("text") == "yes" for b in response_body["content"])


# ---------- model fallback ----------


async def test_model_fallback_when_body_missing(mock_client: dict[str, Any]) -> None:
    """body 没 model + upstream.model 有值 → forwarder 注入 upstream.model。"""
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"messages": []}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(model="claude-haiku-4-5"),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    sent = json.loads(mock_client["request"].content)
    assert sent["model"] == "claude-haiku-4-5"


async def test_model_fallback_when_body_empty_string(mock_client: dict[str, Any]) -> None:
    """body 传 model="" 也算"无 model",同样兜底。"""
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "", "messages": []}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(model="claude-sonnet-4-5"),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    sent = json.loads(mock_client["request"].content)
    assert sent["model"] == "claude-sonnet-4-5"


async def test_model_explicit_overrides_upstream_default(
    mock_client: dict[str, Any],
) -> None:
    """body 显式有 model → 不动,client 的优先级高于 upstream.model。"""
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-opus-4-5", "messages": []}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(model="claude-haiku-4-5"),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    sent = json.loads(mock_client["request"].content)
    assert sent["model"] == "claude-opus-4-5"


async def test_model_no_fallback_when_upstream_has_no_model(
    mock_client: dict[str, Any],
) -> None:
    """body 无 model + upstream 也无 model → 维持原样(让上游自己 4xx)。"""
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"messages": []}).encode("utf-8")
    await forwarder.forward(
        upstream=_anthropic_upstream(model=None),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    sent = json.loads(mock_client["request"].content)
    assert "model" not in sent


async def test_default_max_tokens_added_when_missing_for_responses_to_completions(
    mock_client: dict[str, Any],
) -> None:
    """Responses client 不传 max_output_tokens 时,server 给 completions upstream 补默认值。"""
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

    body = json.dumps({"model": "gpt-4o-mini", "input": "hi"}).encode("utf-8")
    await forwarder.forward(
        upstream=_openai_upstream(),
        server_api=ServerApi.RESPONSES,
        body=body,
        content_type="application/json",
    )

    sent = json.loads(mock_client["request"].content)
    assert sent["max_tokens"] == 32768


async def test_default_max_tokens_does_not_override_explicit_responses_value(
    mock_client: dict[str, Any],
) -> None:
    """客户端显式传 max_output_tokens 时,server 不覆盖。"""
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

    body = json.dumps({"model": "gpt-4o-mini", "input": "hi", "max_output_tokens": 1234}).encode(
        "utf-8"
    )
    await forwarder.forward(
        upstream=_openai_upstream(),
        server_api=ServerApi.RESPONSES,
        body=body,
        content_type="application/json",
    )

    sent = json.loads(mock_client["request"].content)
    assert sent["max_tokens"] == 1234


async def test_default_max_tokens_added_when_missing_for_chat_passthrough(
    mock_client: dict[str, Any],
) -> None:
    """Chat Completions 同格式直通没传 max_tokens 时也补默认值。"""
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "gpt-4o-mini", "messages": []}).encode("utf-8")
    await forwarder.forward(
        upstream=_openai_upstream(),
        server_api=ServerApi.CHAT_COMPLETIONS,
        body=body,
        content_type="application/json",
    )

    sent = json.loads(mock_client["request"].content)
    assert sent["max_tokens"] == 32768


# ---------- extra_response_headers ----------


async def test_extra_response_headers_injected(mock_client: dict[str, Any]) -> None:
    mock_client["handler"] = lambda req: httpx.Response(200, json={})

    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    resp = await forwarder.forward(
        upstream=_anthropic_upstream(),
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
        extra_response_headers={"r-warnings": "store_ignored"},
    )
    assert resp.headers.get("r-warnings") == "store_ignored"


# ---------- 未初始化 client 的防御 ----------


async def test_forward_without_open_raises() -> None:
    """模块级 forwarder 未 open(mock_client fixture 没注入)时,必须抛明确错误而不是默许 None。"""
    assert forwarder._client is None
    body = json.dumps({"model": "claude-haiku-4-5"}).encode("utf-8")
    with pytest.raises(RuntimeError, match="httpx client 未初始化"):
        await forwarder.forward(
            upstream=_anthropic_upstream(),
            server_api=ServerApi.MESSAGES,
            body=body,
            content_type="application/json",
        )


async def test_forwarder_open_disables_trust_env() -> None:
    """上游转发 client 不读取系统代理环境,避免内网 upstream 被代理劫持。"""
    from rosetta.server.service.forwarder import Forwarder

    fwd = Forwarder()
    try:
        await fwd.open()
        client = fwd._get_client()
        assert client._trust_env is False  # pyright: ignore[reportPrivateUsage]
    finally:
        await fwd.close()


# ---------- provider=mock 短路 ----------


def _mock_upstream() -> Upstream:
    return Upstream(
        id="m" * 32,
        name="mock",
        native_api="any",  # mock 不发 HTTP,ServerApi 语义不适用
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
            line[len("data:") :].lstrip() for line in frame.splitlines() if line.startswith("data:")
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
        server_api=ServerApi.MESSAGES,
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
    # 拼回文本后断言 echo 前缀(含 ServerApi)+ 用户输入
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
        server_api=ServerApi.CHAT_COMPLETIONS,
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
        server_api=ServerApi.RESPONSES,
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
        server_api=ServerApi.MESSAGES,
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
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    assert resp.status_code == 200


# ---------- 请求流水落库 ----------


async def test_forward_writes_log_on_success(session: AsyncSession) -> None:
    """每次成功 forward 落 1 条 logs 记录:status=ok、upstream_id、model、latency。"""
    # upstream 要真实存在于 DB(FK 不强制,但用 mock 占位避免发 HTTP)
    mock_up = Upstream(
        id="a" * 32,
        name="mock-log-ok",
        native_api="any",
        provider="mock",
        api_key=None,
        base_url="mock://",
        enabled=True,
    )
    session.add(mock_up)
    await session.commit()

    body = json.dumps(
        {
            "model": "claude-haiku-4-5",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hi"}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=mock_up,
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
        client_addr="127.0.0.1:54321",
    )
    # 消费流(触发完整生命周期)
    if hasattr(resp, "body_iterator"):
        async for _ in resp.body_iterator:  # type: ignore[attr-defined]
            pass

    stmt = select(LogEntry).where(LogEntry.upstream_id == mock_up.id)
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    entry = rows[0]
    assert entry.status == "ok"
    assert entry.model == "claude-haiku-4-5"
    assert entry.error is None
    assert entry.latency_ms is not None and entry.latency_ms >= 0
    # client_addr 透传 + upstream_url 自动从 upstream.base_url 取(mock 写的是 'mock://')
    assert entry.client_addr == "127.0.0.1:54321"
    assert entry.upstream_url == "mock://"
    assert entry.request_text == "hi"
    assert entry.response_text == "hi"
    assert entry.input_tokens is not None and entry.input_tokens > 0
    assert entry.output_tokens is not None and entry.output_tokens > 0


async def test_forward_writes_log_tokens_on_stream_success(session: AsyncSession) -> None:
    mock_up = Upstream(
        id="c" * 32,
        name="mock-log-stream",
        native_api="any",
        provider="mock",
        api_key=None,
        base_url="mock://",
        enabled=True,
    )
    session.add(mock_up)
    await session.commit()

    body = json.dumps(
        {
            "model": "claude-haiku-4-5",
            "max_tokens": 32,
            "stream": True,
            "messages": [{"role": "user", "content": "hello stream"}],
        }
    ).encode("utf-8")
    resp = await forwarder.forward(
        upstream=mock_up,
        server_api=ServerApi.MESSAGES,
        body=body,
        content_type="application/json",
    )
    await _drain_stream(resp)

    stmt = select(LogEntry).where(LogEntry.upstream_id == mock_up.id)
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    entry = rows[0]
    assert entry.status == "ok"
    assert entry.input_tokens is not None and entry.input_tokens > 0
    assert entry.output_tokens is not None and entry.output_tokens > 0


async def test_forward_writes_log_on_service_error(session: AsyncSession) -> None:
    """ServiceError 路径也落一条 logs(status=error, error 字段带 code+msg)。"""
    from rosetta.server.service.exceptions import ServiceError

    mock_up = Upstream(
        id="b" * 32,
        name="mock-log-err",
        native_api="any",
        provider="mock",
        api_key=None,
        base_url="mock://",
        enabled=True,
    )
    session.add(mock_up)
    await session.commit()

    # 非法 JSON body → _parse_body 抛 ServiceError(invalid_json_body)
    with pytest.raises(ServiceError):
        await forwarder.forward(
            upstream=mock_up,
            server_api=ServerApi.MESSAGES,
            body=b"not-json",
            content_type="application/json",
        )

    stmt = select(LogEntry).where(LogEntry.upstream_id == mock_up.id)
    rows = (await session.execute(stmt)).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].error is not None and "invalid_json_body" in rows[0].error


async def test_streaming_log_accepts_memoryview_chunks() -> None:
    """流式日志收集应接受 ASGI 常见的 bytes-like chunk。"""
    from fastapi.responses import StreamingResponse

    captured: dict[str, str | None] = {"response_text": None}

    async def _source() -> AsyncIterator[memoryview]:
        payload = (
            b"event: content_block_delta\n"
            b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}\n\n'
        )
        yield memoryview(payload)

    async def _record_log(
        upstream: Upstream,
        model: str | None,
        status: str,
        t0: float,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        client_addr: str | None = None,
        request_text: str | None = None,
        response_text: str | None = None,
    ) -> None:
        del (
            upstream,
            model,
            status,
            t0,
            input_tokens,
            output_tokens,
            error,
            client_addr,
            request_text,
        )
        captured["response_text"] = response_text

    original = forwarder._record_log
    forwarder._record_log = _record_log
    try:
        resp = StreamingResponse(_source(), media_type="text/event-stream")
        wrapped = forwarder._wrap_streaming_response_for_logging(
            resp,
            upstream=_anthropic_upstream(),
            server_api=ServerApi.MESSAGES,
            model="claude-haiku-4-5",
            t0=0.0,
            request_text="hello",
            client_addr=None,
        )
        body = await _drain_stream(wrapped)
        assert b'"text":"hi"' in body
        assert captured["response_text"] == "hi"
    finally:
        forwarder._record_log = original
