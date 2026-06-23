"""ChatContext 单元测试:流/非流控制 + 响应解析工具函数。

不依赖 server,直接构造 ChatContext + MockClient 验证 run_turn 的流和非流路径,
以及 _extract_non_stream_text / _extract_input_tokens / _extract_output_tokens 的解析行为。
"""

from __future__ import annotations

import pytest
from typing import Any

import httpx
import pytest
import pytest_asyncio

from rosetta.cli.core.context import (
    ChatContext,
    _extract_input_tokens,
    _extract_non_stream_text,
    _extract_output_tokens,
)
from rosetta.sdk.client import ProxyClient
from rosetta.shared.server_api import ServerApi


class _MockClient:
    """轻量 mock,只暴露 post_chat + data_url_and_headers + mode。"""

    def __init__(self, status: int = 200, json_data: dict[str, Any] | None = None) -> None:
        self.mode = "server"
        self._status = status
        self._json = json_data or {}
        self.last_body: dict[str, Any] | None = None
        self.last_override_api_key: str | None = None

    async def post_chat(
        self,
        server_api: ServerApi,
        body: dict[str, Any],
        *,
        override_api_key: str | None = None,
        upstream_header: str | None = None,
    ) -> httpx.Response:
        self.last_body = body
        self.last_override_api_key = override_api_key
        return httpx.Response(self._status, json=self._json)

    def data_url_and_headers(
        self,
        server_api: ServerApi,
        *,
        override_api_key: str | None = None,
        upstream_header: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        return ("http://t/v1/messages", {})




# ---------- _extract_non_stream_text ----------


def test_extract_messages_text() -> None:
    data = {"content": [{"type": "text", "text": "Hello, world!"}]}
    assert _extract_non_stream_text(data, ServerApi.MESSAGES) == "Hello, world!"


def test_extract_messages_multiple_blocks() -> None:
    data = {
        "content": [
            {"type": "text", "text": "Hello"},
            {"type": "tool_use", "name": "get_weather"},
            {"type": "text", "text": "Done"},
        ]
    }
    assert _extract_non_stream_text(data, ServerApi.MESSAGES) == "HelloDone"


def test_extract_messages_empty_content() -> None:
    assert _extract_non_stream_text({}, ServerApi.MESSAGES) == ""
    assert _extract_non_stream_text({"content": []}, ServerApi.MESSAGES) == ""
    assert _extract_non_stream_text({"content": [{"type": "tool_use"}]}, ServerApi.MESSAGES) == ""


def test_extract_completions_text() -> None:
    data = {"choices": [{"message": {"content": "Hi there"}}]}
    assert _extract_non_stream_text(data, ServerApi.CHAT_COMPLETIONS) == "Hi there"


def test_extract_completions_no_choices() -> None:
    assert _extract_non_stream_text({}, ServerApi.CHAT_COMPLETIONS) == ""
    assert _extract_non_stream_text({"choices": []}, ServerApi.CHAT_COMPLETIONS) == ""


def test_extract_responses_text() -> None:
    data = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Result here"}],
            }
        ]
    }
    assert _extract_non_stream_text(data, ServerApi.RESPONSES) == "Result here"


def test_extract_responses_multiple_messages() -> None:
    data = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "First"}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Second"}],
            },
        ]
    }
    assert _extract_non_stream_text(data, ServerApi.RESPONSES) == "FirstSecond"


def test_extract_responses_empty_output() -> None:
    assert _extract_non_stream_text({}, ServerApi.RESPONSES) == ""
    assert _extract_non_stream_text({"output": []}, ServerApi.RESPONSES) == ""


# ---------- _extract_input_tokens / _extract_output_tokens ----------


def test_extract_input_tokens_messages() -> None:
    data = {"usage": {"input_tokens": 42, "output_tokens": 7}}
    assert _extract_input_tokens(data, ServerApi.MESSAGES) == 42
    assert _extract_output_tokens(data, ServerApi.MESSAGES) == 7


def test_extract_input_tokens_completions() -> None:
    data = {"usage": {"prompt_tokens": 10, "completion_tokens": 20}}
    assert _extract_input_tokens(data, ServerApi.CHAT_COMPLETIONS) == 10
    assert _extract_output_tokens(data, ServerApi.CHAT_COMPLETIONS) == 20


def test_extract_tokens_no_usage() -> None:
    assert _extract_input_tokens({}, ServerApi.MESSAGES) == 0
    assert _extract_output_tokens({}, ServerApi.MESSAGES) == 0


def test_extract_tokens_missing_field() -> None:
    data = {"usage": {}}
    assert _extract_input_tokens(data, ServerApi.MESSAGES) == 0
    assert _extract_output_tokens(data, ServerApi.MESSAGES) == 0


def test_extract_tokens_responses_returns_zero() -> None:
    """Responses API 暂不支持 usage 提取。"""
    data = {"usage": {"input_tokens": 5, "output_tokens": 3}}
    assert _extract_input_tokens(data, ServerApi.RESPONSES) == 0
    assert _extract_output_tokens(data, ServerApi.RESPONSES) == 0


# ---------- ChatContext stream field ----------


def test_build_body_stream_true(monkeypatch) -> None:
    ctx = ChatContext(
        client=_MockClient(),  # type: ignore[arg-type]
        server_api=ServerApi.MESSAGES,
        model="claude-4",
        stream=True,
    )
    body = ctx._build_body()
    assert body["stream"] is True


def test_build_body_stream_false(monkeypatch) -> None:
    ctx = ChatContext(
        client=_MockClient(),  # type: ignore[arg-type]
        server_api=ServerApi.MESSAGES,
        model="claude-4",
        stream=False,
    )
    body = ctx._build_body()
    assert body["stream"] is False


@pytest.mark.asyncio
async def test_run_turn_non_stream(monkeypatch) -> None:
    """stream=False 时 run_turn 走非流路径,返回完整文本。"""
    mock = _MockClient(
        json_data={
            "content": [{"type": "text", "text": "Full response"}],
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
    )
    ctx = ChatContext(
        client=mock,  # type: ignore[arg-type]
        server_api=ServerApi.MESSAGES,
        model="claude-4",
        stream=False,
    )
    ctx.append_user("hello")

    tokens: list[str] = []
    result = await ctx.run_turn(on_token=tokens.append)

    assert tokens == ["Full response"]
    assert result.text == "Full response"
    assert result.input_tokens == 5
    assert result.output_tokens == 3


@pytest.mark.asyncio
async def test_run_turn_non_stream_http_error(monkeypatch) -> None:
    """非流式请求遇到 4xx 会抛 ChatError。"""
    from rosetta.cli.core.context import ChatError

    mock = _MockClient(status=400, json_data={"error": "bad request"})
    ctx = ChatContext(
        client=mock,  # type: ignore[arg-type]
        server_api=ServerApi.MESSAGES,
        model="claude-4",
        stream=False,
    )
    ctx.append_user("hi")

    with pytest.raises(ChatError) as excinfo:
        await ctx.run_turn(on_token=lambda t: None)
    assert excinfo.value.status == 400


@pytest.mark.asyncio
async def test_run_turn_non_stream_sends_override_api_key(monkeypatch) -> None:
    """非流式路径也透传 override_api_key。"""
    mock = _MockClient(json_data={"content": [{"type": "text", "text": "ok"}]})
    ctx = ChatContext(
        client=mock,  # type: ignore[arg-type]
        server_api=ServerApi.MESSAGES,
        model="claude-4",
        api_key="sk-override",
        stream=False,
    )
    ctx.append_user("hi")
    await ctx.run_turn(on_token=lambda t: None)

    assert mock.last_override_api_key == "sk-override"


def test_build_body_without_model_omits_field() -> None:
    """model=None 时 body 不写 model 字段,让 server 兜底。"""
    ctx = ChatContext(
        client=_MockClient(),  # type: ignore[arg-type]
        server_api=ServerApi.MESSAGES,
        model=None,
    )
    body = ctx._build_body()
    assert "model" not in body


def test_build_body_completions_stream_false_includes_stream_options_off() -> None:
    """completions 格式 stream=False 时不发 stream_options。"""
    ctx = ChatContext(
        client=_MockClient(),  # type: ignore[arg-type]
        server_api=ServerApi.CHAT_COMPLETIONS,
        model="gpt-4o",
        stream=False,
    )
    body = ctx._build_body()
    assert body["stream"] is False
    assert "stream_options" not in body or body.get("stream_options") == {}


# 需要手动注册 asyncio fixture
# pyright: reportUnusedFunction=false
