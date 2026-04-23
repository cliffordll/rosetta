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


@pytest.mark.parametrize("fixture_name", NONSTREAM_FIXTURES)
def test_response_nonstream_roundtrip(fixture_name: str) -> None:
    body = _load_fixture(fixture_name)["response_nonstream"]

    ir1 = responses_response_to_ir(body)
    body_back = ir_to_responses_response(ir1)
    ir2 = responses_response_to_ir(body_back)

    assert ir1 == ir2, f"{fixture_name}: IR 不等价"
    assert body_back.get("object") == "response"
    assert _strip_nones(body) == _strip_nones(body_back), f"{fixture_name}: 归一化 JSON 不等价"
