"""OpenAI Responses adapter roundtrip 测试(阶段 2.5.1)。

与 messages / completions 对称的双向等价验证:
1. IR 等价:`ir1 == responses_to_ir(ir_to_responses(ir1))`
2. 归一化 JSON 等价:剥 None 值后字典相等

Stream fixture 本次不加(Responses 流式事件面较宽,后续再补):
- stream_simple_text
- stream_with_tool_call
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rosetta.server.translation.responses.request import (
    ir_to_responses,
    responses_to_ir,
)
from rosetta.server.translation.responses.response import (
    ir_to_responses_response,
    responses_response_to_ir,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "responses"


def _load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _strip_nones(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_nones(v) for k, v in value.items() if v is not None}  # type: ignore[misc]
    if isinstance(value, list):
        return [_strip_nones(v) for v in value]  # type: ignore[misc]
    return value


NONSTREAM_FIXTURES = [
    "simple_text",
    "with_instructions",
    "multi_turn",
    "tool_use",
    "tool_result",
    "incomplete_max_tokens",
]


@pytest.mark.parametrize("fixture_name", NONSTREAM_FIXTURES)
def test_request_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["request"]

    ir1 = responses_to_ir(body)
    body_back = ir_to_responses(ir1)
    ir2 = responses_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    assert _strip_nones(body) == _strip_nones(body_back), f"{fixture_name}: 归一化 JSON 不等价"


def test_request_without_max_output_tokens() -> None:
    """Responses 请求允许缺失 max_output_tokens;IR 与回写都不应带出该字段。"""
    body = {"model": "gpt-4.1-mini", "input": "hello"}
    ir = responses_to_ir(body)
    assert ir.max_tokens is None
    body_back = ir_to_responses(ir)
    assert "max_output_tokens" not in body_back


def test_request_skips_compaction_input_items() -> None:
    """Responses input 中的 compaction item 跨格式翻译时无对应物,应跳过。"""
    body = {
        "model": "gpt-4.1-mini",
        "input": [
            {"type": "message", "role": "user", "content": "hi"},
            {"type": "compaction", "data": {"summary": "some context"}},
            {"type": "message", "role": "assistant", "content": "hello"},
        ],
    }
    ir = responses_to_ir(body)
    assert len(ir.messages) == 2
    assert ir.messages[0].role == "user"
    assert ir.messages[1].role == "assistant"


def test_request_skips_reasoning_input_items() -> None:
    """Responses input 中的 reasoning item 跨格式翻译时无对应物,应跳过。"""
    body = {
        "model": "gpt-4.1-mini",
        "input": [
            {"type": "message", "role": "user", "content": "hi"},
            {
                "type": "reasoning",
                "content": [{"type": "output_text", "text": "let me think..."}],
            },
            {"type": "message", "role": "assistant", "content": "hello"},
        ],
    }
    ir = responses_to_ir(body)
    assert len(ir.messages) == 2
    assert ir.messages[0].role == "user"
    assert ir.messages[1].role == "assistant"


def test_request_custom_tool_call_maps_to_tool_use() -> None:
    """Responses input 中的 custom_tool_call 应映射为 IR ToolUseBlock。"""
    body = {
        "model": "gpt-4.1-mini",
        "input": [
            {"type": "message", "role": "user", "content": "search"},
            {
                "type": "custom_tool_call",
                "call_id": "call_abc",
                "name": "my_custom_tool",
                "arguments": '{"query":"python"}',
            },
        ],
    }
    ir = responses_to_ir(body)
    assert len(ir.messages) == 2
    assert ir.messages[1].role == "assistant"
    tool_use = ir.messages[1].content[0]
    assert tool_use.type == "tool_use"
    assert tool_use.id == "call_abc"  # type: ignore[union-attr]
    assert tool_use.name == "my_custom_tool"  # type: ignore[union-attr]
    assert tool_use.input == {"query": "python"}  # type: ignore[union-attr]


def test_request_custom_tool_call_output_maps_to_tool_result() -> None:
    """Responses input 中的 custom_tool_call_output 应映射为 IR ToolResultBlock。"""
    body = {
        "model": "gpt-4.1-mini",
        "input": [
            {"type": "message", "role": "user", "content": "search"},
            {
                "type": "custom_tool_call_output",
                "call_id": "call_abc",
                "output": "search results",
            },
        ],
    }
    ir = responses_to_ir(body)
    assert len(ir.messages) == 2
    assert ir.messages[0].role == "user"
    tool_result = ir.messages[1].content[0]
    assert tool_result.type == "tool_result"
    assert tool_result.tool_use_id == "call_abc"  # type: ignore[union-attr]
    assert tool_result.content == "search results"  # type: ignore[union-attr]


@pytest.mark.parametrize("fixture_name", NONSTREAM_FIXTURES)
def test_response_nonstream_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["response_nonstream"]

    ir1 = responses_response_to_ir(body)
    body_back = ir_to_responses_response(ir1)
    ir2 = responses_response_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    assert body_back.get("object") == "response"
    assert _strip_nones(body) == _strip_nones(body_back), f"{fixture_name}: 归一化 JSON 不等价"
