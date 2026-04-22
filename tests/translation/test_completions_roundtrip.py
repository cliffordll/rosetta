"""OpenAI Chat Completions adapter roundtrip 测试(阶段 2.2)。

策略与 `test_messages_roundtrip.py` 对称:对每个 fixture 做双向验证
1. IR 等价:`ir1 == messages_to_ir(ir_to_messages(ir1))`
2. 归一化 JSON 等价:剥 None 值后字典相等(容忍 `null ≡ missing`)

fixture 只写 adapter 会产出的字段形状(stream 不写 `stream_options`,非 nonstream
不写 `n` 等 v0.1 未支持字段)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rosetta.server.translation.completions.request import (
    completions_to_ir,
    ir_to_completions,
)
from rosetta.server.translation.completions.response import (
    completions_response_to_ir,
    completions_stream_to_ir,
    ir_to_completions_response,
    ir_to_completions_stream,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "completions"


def _load_fixture(name: str) -> dict[str, Any]:
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


def _strip_nones(value: Any) -> Any:
    """递归剥掉字典里值为 None 的键,便于容忍 null ≡ missing。"""
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
    "finish_length",
]

STREAM_FIXTURES = [
    "stream_simple_text",
    "stream_with_tool_calls",
]

REQUEST_FIXTURES = NONSTREAM_FIXTURES + STREAM_FIXTURES


@pytest.mark.parametrize("fixture_name", REQUEST_FIXTURES)
def test_request_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["request"]

    ir1 = completions_to_ir(body)
    body_back = ir_to_completions(ir1)
    ir2 = completions_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    assert _strip_nones(body) == _strip_nones(body_back), (
        f"{fixture_name}: 归一化 JSON 不等价"
    )


@pytest.mark.parametrize("fixture_name", NONSTREAM_FIXTURES)
def test_response_nonstream_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["response_nonstream"]

    ir1 = completions_response_to_ir(body)
    body_back = ir_to_completions_response(ir1)
    ir2 = completions_response_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    assert body_back.get("object") == "chat.completion"
    assert _strip_nones(body) == _strip_nones(body_back), (
        f"{fixture_name}: 归一化 JSON 不等价"
    )


@pytest.mark.parametrize("fixture_name", STREAM_FIXTURES)
def test_response_stream_roundtrip(fixture_name: str) -> None:
    chunks = _load_fixture(fixture_name)["response_stream"]

    ir_events_1 = list(completions_stream_to_ir(chunks))
    chunks_back = list(ir_to_completions_stream(ir_events_1))
    ir_events_2 = list(completions_stream_to_ir(chunks_back))

    assert ir_events_1 == ir_events_2, f"{fixture_name}: IR 事件序列不等价"
    # chunks 数量可以不严格相同(上游多余 role chunk 会被合并),只对齐语义等价
    # 这里通过"双向 IR 等价"已保证语义;不额外要求 chunk 数相等
