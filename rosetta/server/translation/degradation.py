"""阶段 2.5.2:Responses API 有状态特性 / 内置工具的降级策略。

进入翻译链之前由此模块对 Responses 请求做"降级"处理:
- 有状态字段:`previous_response_id`、`background=True`
  → 当目标不是 Responses 格式时,直接抛 `StatefulNotTranslatableError`(dataplane 捕获后
  返回 HTTP 400,`error.code="stateful_not_translatable"`)
- 可忽略字段:`store=True`
  → 剥除 + 记一个 warning(`store_ignored`)
- 内置 tools(`web_search` / `file_search` / `computer_use` 等非 function 类型)
  → 从 tools 数组剥除 + 记 warning(`builtin_tools_removed:<name>`)

warnings 以 CSV 格式拼装在响应头 `x-rosetta-warnings`(DESIGN §8.3 规范)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from rosetta.shared.protocols import Protocol


class StatefulNotTranslatableError(ValueError):
    """有状态字段无法降级,必须在 dataplane 翻成 HTTP 400。"""

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name
        super().__init__(f"Responses 有状态字段 `{field_name}` 无法翻译到非 Responses 上游")


def _empty_str_list() -> list[str]:
    return []


@dataclass
class DegradationResult:
    """降级输出:新请求 body + 收集到的 warning 标记。"""

    body: dict[str, Any]
    warnings: list[str] = field(default_factory=_empty_str_list)

    def warnings_header(self) -> str | None:
        """拼装成 `x-rosetta-warnings` 响应头值(CSV);无 warning 返回 None。"""
        return ",".join(self.warnings) if self.warnings else None


# 有状态字段:目标非 Responses 时无法翻译,必须 raise
_STATEFUL_BLOCKING = ("previous_response_id",)

# 内置工具类型(非 `function`)
_KNOWN_BUILTIN_TOOL_TYPES = frozenset(
    {"web_search", "file_search", "computer_use", "code_interpreter"}
)


def degrade_responses_request(
    body: dict[str, Any], *, target_protocol: Protocol
) -> DegradationResult:
    """对 Responses 请求 body 做降级。

    - 若 `target_protocol is Protocol.RESPONSES`:不降级,原样返回(仍剥 warning 标记为空)
    - 否则按规则剥除 / 抛错
    """
    if target_protocol is Protocol.RESPONSES:
        return DegradationResult(body=body, warnings=[])

    new_body = dict(body)
    warnings: list[str] = []

    # 有状态 - 阻断
    for fname in _STATEFUL_BLOCKING:
        if fname in new_body and new_body[fname] is not None:
            raise StatefulNotTranslatableError(fname)

    # background=True:阻断(v0.1 根本不支持 background 任务语义)
    if new_body.get("background") is True:
        raise StatefulNotTranslatableError("background")

    # store=True:剥除 + warning
    if new_body.pop("store", None) is True:
        warnings.append("store_ignored")
    else:
        # store=False 或缺失也剥掉,保持 body 干净
        new_body.pop("store", None)

    # 内置 tools:剥除 + warning(每个 tool 一条)
    if "tools" in new_body:
        raw_tools = new_body["tools"]
        if isinstance(raw_tools, list):
            filtered_tools: list[dict[str, Any]] = []
            for raw_tool in cast(list[Any], raw_tools):
                if isinstance(raw_tool, dict):
                    t = cast(dict[str, Any], raw_tool)
                    ttype = t.get("type")
                    if ttype == "function":
                        filtered_tools.append(t)
                    elif isinstance(ttype, str) and (
                        ttype in _KNOWN_BUILTIN_TOOL_TYPES or ttype != "function"
                    ):
                        warnings.append(f"builtin_tools_removed:{ttype}")
                    else:
                        # 未知形状,raise 让上层早知道(与 IR 的 extra=forbid 一致)
                        raise ValueError(f"tools[] 不识别的 type: {ttype!r}")
                else:
                    raise ValueError(f"tools[] 元素必须是 dict,收到 {type(raw_tool).__name__}")
            if filtered_tools:
                new_body["tools"] = filtered_tools
            else:
                new_body.pop("tools", None)

    # previous_response_id 已在 _STATEFUL_BLOCKING 检查;background 同上;剩余字段原样透传给 adapter

    return DegradationResult(body=new_body, warnings=warnings)
