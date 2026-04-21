"""OpenAI Responses API 请求体 ↔ RequestIR。

Responses 的 input 拓扑比较灵活:可以是 str(简化版)也可以是 item 数组。
item 类型:`message` / `function_call` / `function_call_output`(还有 `reasoning`
等 assistant-emitted,v0.1 不支持)。

对应关系(IR 以 Anthropic 风为基准):
- `instructions` → IR `system`
- `input` 的 `message` items → IR messages
- `input` 的 `function_call` items(assistant)→ IR `ToolUseBlock`
  追加到前一条 assistant Message 或新开一条 assistant Message
- `input` 的 `function_call_output` items → IR `ToolResultBlock`
  前置到下一条 user Message 或独立成 user Message

未支持字段 raise;`store` / `previous_response_id` / `background`
/ 内置 tools 由 degradation 层先剥再进这里(v0.1 不在 adapter 内处理)。
"""

from __future__ import annotations

import json
from typing import Any, cast

from rosetta.server.translation.ir import (
    ContentBlock,
    Message,
    RequestIR,
    SystemPrompt,
    TextBlock,
    Tool,
    ToolChoice,
    ToolChoiceAny,
    ToolChoiceAuto,
    ToolChoiceNone,
    ToolResultBlock,
    ToolUseBlock,
)

_SUPPORTED_REQ_KEYS: frozenset[str] = frozenset(
    {
        "model",
        "input",
        "instructions",
        "max_output_tokens",
        "temperature",
        "top_p",
        "tools",
        "tool_choice",
        "stream",
    }
)


# ---------- Responses → IR ----------


def responses_to_ir(body: dict[str, Any]) -> RequestIR:
    """OpenAI /v1/responses 请求体 → RequestIR。"""
    unsupported = set(body.keys()) - _SUPPORTED_REQ_KEYS
    if unsupported:
        raise ValueError(f"不支持的 Responses 请求字段: {sorted(unsupported)}")
    if "model" not in body:
        raise ValueError("Responses 请求缺少必需字段: model")
    if "input" not in body:
        raise ValueError("Responses 请求缺少必需字段: input")
    if "max_output_tokens" not in body:
        raise ValueError("Responses 请求缺少必需字段: max_output_tokens")

    instructions_val = body.get("instructions")
    system: str | None
    if instructions_val is None:
        system = None
    elif isinstance(instructions_val, str):
        system = instructions_val
    else:
        raise ValueError("instructions 必须是 str 或缺失")

    messages = _input_to_ir_messages(body["input"])

    payload: dict[str, Any] = {
        "model": body["model"],
        "messages": [m.model_dump(exclude_none=True) for m in messages],
        "max_tokens": body["max_output_tokens"],
    }
    if system is not None:
        payload["system"] = system
    for key in ("temperature", "top_p", "stream"):
        if key in body:
            payload[key] = body[key]
    if "tools" in body:
        payload["tools"] = [
            _tool_responses_to_ir(t) for t in cast(list[dict[str, Any]], body["tools"])
        ]
    if "tool_choice" in body:
        payload["tool_choice"] = _tool_choice_responses_to_ir(body["tool_choice"])

    return RequestIR.model_validate(payload)


def _input_to_ir_messages(input_val: Any) -> list[Message]:
    """Responses `input` 字段 → IR Messages。

    `input` 可以是:
    - str:shortcut,直接变成一条 user 消息,content=[TextBlock(str)]
    - list[item]:按 item.type 分派
    """
    if isinstance(input_val, str):
        return [Message(role="user", content=[TextBlock(text=input_val)])]
    if not isinstance(input_val, list):
        raise ValueError(f"input 必须是 str 或 list,收到 {type(input_val).__name__}")

    result: list[Message] = []
    pending_tool_results: list[ToolResultBlock] = []

    def flush_pending() -> None:
        if pending_tool_results:
            result.append(Message(role="user", content=list(pending_tool_results)))
            pending_tool_results.clear()

    for raw_item in cast(list[Any], input_val):
        if not isinstance(raw_item, dict):
            raise ValueError(f"input item 必须是 dict: {raw_item!r}")
        item = cast(dict[str, Any], raw_item)
        itype = item.get("type")

        if itype == "message":
            role = item.get("role")
            if role == "system":
                raise ValueError("Responses input 不应含 role=system(请用顶层 instructions)")
            if role not in ("user", "assistant"):
                raise ValueError(f"input message 的 role 不支持: {role!r}")
            content_parts = item.get("content")
            blocks = _message_content_to_blocks(content_parts, role=role)
            if role == "user":
                merged: list[ContentBlock] = [*pending_tool_results, *blocks]
                pending_tool_results.clear()
                if not merged:
                    raise ValueError("user message content 不能为空")
                result.append(Message(role="user", content=merged))
            else:
                flush_pending()
                if not blocks:
                    raise ValueError("assistant message content 不能为空")
                result.append(Message(role="assistant", content=blocks))

        elif itype == "function_call":
            flush_pending()
            call_id = item.get("call_id")
            name = item.get("name")
            args_str = item.get("arguments", "")
            if not isinstance(call_id, str):
                raise ValueError("function_call.call_id 必须是 str")
            if not isinstance(name, str):
                raise ValueError("function_call.name 必须是 str")
            if not isinstance(args_str, str):
                raise ValueError("function_call.arguments 必须是 str(JSON 字符串)")
            parsed: dict[str, Any] = (
                cast(dict[str, Any], json.loads(args_str)) if args_str.strip() else {}
            )
            tool_use = ToolUseBlock(id=call_id, name=name, input=parsed)
            # 合并进前一条 assistant(若是),否则新开一条
            if result and result[-1].role == "assistant":
                result[-1].content.append(tool_use)
            else:
                result.append(Message(role="assistant", content=[tool_use]))

        elif itype == "function_call_output":
            call_id = item.get("call_id")
            output = item.get("output")
            if not isinstance(call_id, str):
                raise ValueError("function_call_output.call_id 必须是 str")
            if isinstance(output, str):
                tr_content: str | list[TextBlock] = output
            elif isinstance(output, list):
                blocks_out: list[TextBlock] = []
                for raw_part in cast(list[Any], output):
                    if not isinstance(raw_part, dict):
                        raise ValueError(
                            f"function_call_output.output part 必须是 dict: {raw_part!r}"
                        )
                    p = cast(dict[str, Any], raw_part)
                    if p.get("type") not in ("output_text", "input_text"):
                        raise ValueError(
                            f"function_call_output.output 不支持的 part: {p.get('type')!r}"
                        )
                    blocks_out.append(TextBlock(text=str(p.get("text", ""))))
                tr_content = blocks_out
            else:
                raise ValueError(
                    f"function_call_output.output 必须是 str / list,收到 {type(output).__name__}"
                )
            pending_tool_results.append(ToolResultBlock(tool_use_id=call_id, content=tr_content))

        else:
            raise ValueError(f"不支持的 input item.type: {itype!r}")

    flush_pending()
    return result


def _message_content_to_blocks(content: Any, role: str) -> list[ContentBlock]:
    """message.content(list of parts 或 str)→ IR ContentBlock 列表。"""
    if isinstance(content, str):
        return [TextBlock(text=content)]
    if not isinstance(content, list):
        raise ValueError(f"message.content 必须是 str 或 list,收到 {type(content).__name__}")
    blocks: list[ContentBlock] = []
    for raw_part in cast(list[Any], content):
        if not isinstance(raw_part, dict):
            raise ValueError(f"message.content part 必须是 dict: {raw_part!r}")
        p = cast(dict[str, Any], raw_part)
        ptype = p.get("type")
        # user 用 input_text,assistant 用 output_text;此处容忍任一,部分客户端混用
        if ptype in ("input_text", "output_text"):
            blocks.append(TextBlock(text=str(p.get("text", ""))))
        else:
            raise ValueError(f"message.content 不支持的 part.type: {ptype!r} (role={role})")
    return blocks


def _tool_responses_to_ir(t: dict[str, Any]) -> dict[str, Any]:
    if t.get("type") != "function":
        raise ValueError(
            f"v0.1 仅支持 tools[].type=function,收到 {t.get('type')!r} "
            "(内置 tool 由 degradation 层剥除)"
        )
    # Responses 的 function tool 结构是 flat(name/description/parameters 直接在对象上,
    # 不像 Chat Completions 有嵌套的 function 子对象)
    name = t.get("name")
    if not isinstance(name, str):
        raise ValueError("tools[].name 必须是 str")
    out: dict[str, Any] = {
        "name": name,
        "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
    }
    if "description" in t:
        out["description"] = t["description"]
    return out


def _tool_choice_responses_to_ir(tc: Any) -> dict[str, Any]:
    if tc == "auto":
        return {"type": "auto"}
    if tc == "none":
        return {"type": "none"}
    if tc == "required":
        return {"type": "any"}
    if isinstance(tc, dict):
        tc_d = cast(dict[str, Any], tc)
        if tc_d.get("type") == "function":
            name = tc_d.get("name")
            if not isinstance(name, str):
                raise ValueError("tool_choice.name 必须是 str")
            return {"type": "tool", "name": name}
    raise ValueError(f"不支持的 tool_choice: {tc!r}")


# ---------- IR → Responses ----------


def ir_to_responses(ir: RequestIR) -> dict[str, Any]:
    """RequestIR → OpenAI /v1/responses 请求体。"""
    if ir.top_k is not None:
        raise ValueError("Responses 不支持 top_k")
    if ir.thinking is not None:
        raise ValueError("Responses 不支持 thinking")
    if ir.metadata is not None:
        raise ValueError("Responses 不支持 metadata")
    if ir.stop_sequences:
        raise ValueError("Responses 不支持 stop_sequences")

    body: dict[str, Any] = {
        "model": ir.model,
        "input": _ir_messages_to_input(ir.messages),
        "max_output_tokens": ir.max_tokens,
    }
    if ir.system is not None:
        body["instructions"] = _system_to_instructions(ir.system)
    if ir.temperature is not None:
        body["temperature"] = ir.temperature
    if ir.top_p is not None:
        body["top_p"] = ir.top_p
    if ir.stream is not None:
        body["stream"] = ir.stream
    if ir.tools is not None:
        body["tools"] = [_tool_ir_to_responses(t) for t in ir.tools]
    if ir.tool_choice is not None:
        body["tool_choice"] = _tool_choice_ir_to_responses(ir.tool_choice)
    return body


def _system_to_instructions(system: SystemPrompt) -> str:
    if isinstance(system, str):
        return system
    return "".join(b.text for b in system)


def _ir_messages_to_input(messages: list[Message]) -> list[dict[str, Any]]:
    """IR Messages → Responses `input` item 数组。"""
    out: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "user":
            out.extend(_ir_user_msg_to_items(msg))
        else:
            out.extend(_ir_assistant_msg_to_items(msg))
    return out


def _ir_user_msg_to_items(msg: Message) -> list[dict[str, Any]]:
    """IR user Message → 若干 function_call_output + 可选一条 user message。"""
    tool_results: list[ToolResultBlock] = []
    text_blocks: list[TextBlock] = []
    for block in msg.content:
        if isinstance(block, ToolResultBlock):
            tool_results.append(block)
        elif isinstance(block, TextBlock):
            text_blocks.append(block)
        else:
            raise ValueError(f"Responses user 消息不支持的 block: {type(block).__name__}")

    out: list[dict[str, Any]] = []
    for tr in tool_results:
        if tr.is_error:
            raise ValueError("Responses 不支持 tool_result.is_error;v0.1 不做 error-text 兜底")
        if isinstance(tr.content, str):
            output_val: str | list[dict[str, Any]] = tr.content
        else:
            output_val = [{"type": "output_text", "text": b.text} for b in tr.content]
        out.append(
            {
                "type": "function_call_output",
                "call_id": tr.tool_use_id,
                "output": output_val,
            }
        )

    if text_blocks:
        out.append(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": b.text} for b in text_blocks],
            }
        )
    return out


def _ir_assistant_msg_to_items(msg: Message) -> list[dict[str, Any]]:
    """IR assistant Message → 可选一条 message item + 若干 function_call items。"""
    text_blocks: list[TextBlock] = []
    tool_uses: list[ToolUseBlock] = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            text_blocks.append(block)
        elif isinstance(block, ToolUseBlock):
            tool_uses.append(block)
        else:
            raise ValueError(f"Responses assistant 消息不支持的 block: {type(block).__name__}")

    out: list[dict[str, Any]] = []
    if text_blocks:
        out.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": b.text} for b in text_blocks],
            }
        )
    for tu in tool_uses:
        out.append(
            {
                "type": "function_call",
                "call_id": tu.id,
                "name": tu.name,
                "arguments": json.dumps(tu.input, ensure_ascii=False),
            }
        )
    return out


def _tool_ir_to_responses(t: Tool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "function",
        "name": t.name,
        "parameters": t.input_schema,
    }
    if t.description is not None:
        out["description"] = t.description
    return out


def _tool_choice_ir_to_responses(tc: ToolChoice) -> Any:
    if isinstance(tc, ToolChoiceAuto):
        return "auto"
    if isinstance(tc, ToolChoiceNone):
        return "none"
    if isinstance(tc, ToolChoiceAny):
        return "required"
    # union 穷尽:narrow 到 ToolChoiceTool
    return {"type": "function", "name": tc.name}
