"""Responses 请求降级(2.5.2)单元测试。

覆盖 `rosetta.server.translation.degradation.degrade_responses_request` 的所有分支:
- target=RESPONSES:直通,不剥不 raise
- previous_response_id / background=True:raise `StatefulNotTranslatableError`
- store=True / store=False:剥除 body;True 时追 `store_ignored` warning
- tools 内置类型(web_search / file_search / 等)剥除 + `builtin_tools_removed:<name>` warning
- tools 混合 function + 内置:只保留 function,剥净后 tools 字段消失
- 未知 tool 形状 / 非 dict 元素:raise ValueError
- warnings_header CSV 拼装
"""

from __future__ import annotations

from typing import Any

import pytest

from rosetta.server.translation.degradation import (
    DegradationResult,
    StatefulNotTranslatableError,
    degrade_responses_request,
)
from rosetta.shared.protocols import Protocol


def _base() -> dict[str, Any]:
    """构造一个最小的合法 Responses 请求体,用于各用例上叠字段。"""
    return {"model": "gpt-4.1-mini", "input": "hello"}


# ---------- target = RESPONSES:不降级 ----------


def test_target_responses_passthrough() -> None:
    body = _base() | {"store": True, "previous_response_id": "resp_xxx"}
    result = degrade_responses_request(body, target_protocol=Protocol.RESPONSES)

    # target=RESPONSES 时原样返回,不剥 store 也不 raise previous_response_id
    assert result.body is body
    assert result.warnings == []
    assert result.warnings_header() is None


# ---------- 有状态字段:raise ----------


@pytest.mark.parametrize("target", [Protocol.MESSAGES, Protocol.CHAT_COMPLETIONS])
def test_previous_response_id_raises(target: Protocol) -> None:
    body = _base() | {"previous_response_id": "resp_abc"}
    with pytest.raises(StatefulNotTranslatableError) as exc:
        degrade_responses_request(body, target_protocol=target)
    assert exc.value.field_name == "previous_response_id"


def test_previous_response_id_none_passes() -> None:
    body = _base() | {"previous_response_id": None}
    # None 视作未设置,不应 raise
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert result.warnings == []


def test_background_true_raises() -> None:
    body = _base() | {"background": True}
    with pytest.raises(StatefulNotTranslatableError) as exc:
        degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert exc.value.field_name == "background"


def test_background_false_passes() -> None:
    body = _base() | {"background": False}
    result = degrade_responses_request(body, target_protocol=Protocol.CHAT_COMPLETIONS)
    # background=False 不触发降级;字段在 body 里原样留着(adapter 后续决定)
    assert result.warnings == []


# ---------- store 字段:剥除 + warning ----------


def test_store_true_stripped_with_warning() -> None:
    body = _base() | {"store": True}
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert "store" not in result.body
    assert result.warnings == ["store_ignored"]
    assert result.warnings_header() == "store_ignored"


def test_store_false_stripped_no_warning() -> None:
    body = _base() | {"store": False}
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert "store" not in result.body  # store=False 也被剥掉保持干净
    assert result.warnings == []


# ---------- 内置 tools:剥除 + warning ----------


@pytest.mark.parametrize(
    "builtin_type", ["web_search", "file_search", "computer_use", "code_interpreter"]
)
def test_builtin_tool_stripped(builtin_type: str) -> None:
    body = _base() | {"tools": [{"type": builtin_type}]}
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert "tools" not in result.body  # 剥净后字段消失,不留空数组
    assert result.warnings == [f"builtin_tools_removed:{builtin_type}"]


def test_function_tool_preserved() -> None:
    function_tool = {
        "type": "function",
        "name": "get_weather",
        "parameters": {"type": "object", "properties": {}},
    }
    body = _base() | {"tools": [function_tool]}
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert result.body["tools"] == [function_tool]
    assert result.warnings == []


def test_mixed_tools_keep_function_strip_builtin() -> None:
    function_tool = {"type": "function", "name": "fn", "parameters": {}}
    body = _base() | {
        "tools": [
            function_tool,
            {"type": "web_search"},
            {"type": "file_search"},
        ]
    }
    result = degrade_responses_request(body, target_protocol=Protocol.CHAT_COMPLETIONS)
    assert result.body["tools"] == [function_tool]
    assert result.warnings == [
        "builtin_tools_removed:web_search",
        "builtin_tools_removed:file_search",
    ]
    assert result.warnings_header() == (
        "builtin_tools_removed:web_search,builtin_tools_removed:file_search"
    )


def test_all_builtin_tools_stripped_field_removed() -> None:
    body = _base() | {
        "tools": [{"type": "web_search"}, {"type": "code_interpreter"}]
    }
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert "tools" not in result.body


# ---------- 异常形状 ----------


def test_unknown_tool_type_raises() -> None:
    body = _base() | {"tools": [{"type": None}]}
    with pytest.raises(ValueError, match="不识别的 type"):
        degrade_responses_request(body, target_protocol=Protocol.MESSAGES)


def test_tool_non_dict_raises() -> None:
    body = _base() | {"tools": ["not_a_dict"]}
    with pytest.raises(ValueError, match="必须是 dict"):
        degrade_responses_request(body, target_protocol=Protocol.MESSAGES)


def test_tools_non_list_silently_passes() -> None:
    # 当前实现只处理 list;非 list 直接放过由 adapter 后续报错
    body = _base() | {"tools": "not_a_list"}
    result = degrade_responses_request(body, target_protocol=Protocol.MESSAGES)
    assert result.body["tools"] == "not_a_list"


# ---------- DegradationResult 构造 ----------


def test_degradation_result_default_warnings() -> None:
    r = DegradationResult(body={})
    assert r.warnings == []
    assert r.warnings_header() is None


def test_degradation_result_csv_multiple() -> None:
    r = DegradationResult(body={}, warnings=["a", "b", "c"])
    assert r.warnings_header() == "a,b,c"
