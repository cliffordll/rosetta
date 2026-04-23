"""Anthropic Messages adapter roundtrip 测试。

策略:对每个 fixture 做双向验证
1. IR 等价:`ir1 = load(body); body' = dump(ir1); ir2 = load(body'); assert ir1 == ir2`
   保证 adapter 不丢失语义信息。
2. 归一化 JSON 等价:剥掉 body 里的 `null` 值和 body' 里的 `null` 值后字典相等。
   保证 adapter 不产生幽灵字段或形状偏移。

fixture 里不写显式 `null`(等价于字段缺失),dump 侧用 `exclude_none=True`,
两侧对齐在"字段缺失 = None"的语义上。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rosetta.server.translation.messages.request import (
    ir_to_messages,
    messages_to_ir,
)
from rosetta.server.translation.messages.response import (
    ir_to_messages_response,
    ir_to_messages_stream,
    messages_response_to_ir,
    messages_stream_to_ir,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "messages"


def _load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _strip_nones(value: Any) -> Any:
    """递归剥掉字典里值为 None 的键,便于 JSON 级等价比较容忍 null ≡ missing。"""
    if isinstance(value, dict):
        return {k: _strip_nones(v) for k, v in value.items() if v is not None}  # type: ignore[misc]
    if isinstance(value, list):
        return [_strip_nones(v) for v in value]  # type: ignore[misc]
    return value


NONSTREAM_FIXTURES = [
    "simple_text",
    "with_system",
    "multi_turn",
    "tool_use",
    "tool_result",
    "thinking_plain",
    "thinking_redacted",
]

STREAM_FIXTURES = [
    "stream_simple_text",
    "stream_with_tool_use",
    "stream_with_thinking",
]


# 请求 roundtrip:非流式 fixture 都带 request;流式 fixture 的 request 只多了 `stream: true`,一并覆盖
REQUEST_FIXTURES = NONSTREAM_FIXTURES + STREAM_FIXTURES


@pytest.mark.parametrize("fixture_name", REQUEST_FIXTURES)
def test_request_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["request"]

    ir1 = messages_to_ir(body)
    body_back = ir_to_messages(ir1)
    ir2 = messages_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    assert _strip_nones(body) == _strip_nones(body_back), f"{fixture_name}: 归一化 JSON 不等价"


def test_request_str_content_shorthand() -> None:
    """Anthropic API 允许 `content: "..."` 的 str shorthand,IR 只收 list,
    adapter 入口应把 str 规范化成 `[{"type":"text","text":...}]`。"""
    body = {
        "model": "claude-sonnet-4-5",
        "max_tokens": 16,
        "messages": [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            {"role": "user", "content": "再说一遍"},
        ],
    }

    ir = messages_to_ir(body)

    assert len(ir.messages) == 3
    assert ir.messages[0].content[0].type == "text"
    assert ir.messages[0].content[0].text == "你好"  # type: ignore[union-attr]
    assert ir.messages[1].content[0].text == "hi"  # type: ignore[union-attr]
    assert ir.messages[2].content[0].text == "再说一遍"  # type: ignore[union-attr]


@pytest.mark.parametrize("fixture_name", NONSTREAM_FIXTURES)
def test_response_nonstream_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["response_nonstream"]

    ir1 = messages_response_to_ir(body)
    body_back = ir_to_messages_response(ir1)
    ir2 = messages_response_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    # Anthropic 响应顶层 `type: "message"` 必须保留
    assert body_back.get("type") == "message"
    assert _strip_nones(body) == _strip_nones(body_back), f"{fixture_name}: 归一化 JSON 不等价"


@pytest.mark.parametrize("fixture_name", STREAM_FIXTURES)
def test_response_stream_roundtrip(fixture_name: str) -> None:
    events = _load_fixture(fixture_name)["response_stream"]

    ir_events_1 = list(messages_stream_to_ir(events))
    events_back = list(ir_to_messages_stream(ir_events_1))
    ir_events_2 = list(messages_stream_to_ir(events_back))

    assert ir_events_1 == ir_events_2, f"{fixture_name}: IR 事件序列不等价"
    assert len(events) == len(events_back), (
        f"{fixture_name}: 事件数量不一致 ({len(events)} → {len(events_back)})"
    )
    # 归一化 JSON 逐事件对比(剥 null 容忍 Anthropic 下发字段的 null vs missing 差异)
    for i, (orig, back) in enumerate(zip(events, events_back, strict=True)):
        assert _strip_nones(orig) == _strip_nones(back), (
            f"{fixture_name}[{i}]({orig.get('type')}): 归一化 JSON 不等价"
        )
