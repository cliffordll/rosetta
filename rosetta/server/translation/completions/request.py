"""OpenAI Chat Completions 请求体 ↔ RequestIR。

双向映射规则详见 `completions/__init__.py` 的模块级说明。

核心拓扑差异:
- OpenAI 的 `role="system"` 是 messages 数组首条;IR 的 `system` 是顶层字段。
- OpenAI 的 `role="tool"` 消息承载工具返回;IR 把 tool_result 作为 content block
  放在 user 消息里 —— adapter 负责两种拓扑的互转。
- OpenAI `tool_calls[].function.arguments` 是 JSON 字符串;IR `ToolUseBlock.input`
  是已解析的 dict(请求侧的 arguments 一定是完整 JSON,不会有流式分片)。
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

# Chat Completions 请求顶层字段白名单;其余字段遇到就 raise
_SUPPORTED_REQ_KEYS: frozenset[str] = frozenset(
    {
        "model",
        "messages",
        "tools",
        "tool_choice",
        "max_tokens",
        "temperature",
        "top_p",
        "stop",
        "stream",
    }
)


# ---------- OpenAI → IR ----------


def completions_to_ir(body: dict[str, Any]) -> RequestIR:
    """OpenAI /v1/chat/completions 请求体 → RequestIR。"""
    unsupported = set(body.keys()) - _SUPPORTED_REQ_KEYS
    if unsupported:
        raise ValueError(f"不支持的 Chat Completions 请求字段: {sorted(unsupported)}")
    for required in ("model", "messages", "max_tokens"):
        if required not in body:
            raise ValueError(f"Chat Completions 请求缺少必需字段: {required}")

    messages_raw = body["messages"]
    if not isinstance(messages_raw, list):
        raise ValueError("messages 必须是 list")

    system, messages = _messages_openai_to_ir(cast(list[Any], messages_raw))

    payload: dict[str, Any] = {
        "model": body["model"],
        "messages": [m.model_dump(exclude_none=True) for m in messages],
        "max_tokens": body["max_tokens"],
    }
    if system is not None:
        payload["system"] = system
    for key in ("temperature", "top_p", "stream"):
        if key in body:
            payload[key] = body[key]
    if "stop" in body:
        stop = body["stop"]
        payload["stop_sequences"] = [stop] if isinstance(stop, str) else list(cast(list[str], stop))
    if "tools" in body:
        payload["tools"] = [
            _tool_openai_to_ir(t) for t in cast(list[dict[str, Any]], body["tools"])
        ]
    if "tool_choice" in body:
        payload["tool_choice"] = _tool_choice_openai_to_ir(body["tool_choice"])

    return RequestIR.model_validate(payload)


def _messages_openai_to_ir(
    msgs: list[Any],
) -> tuple[str | None, list[Message]]:
    """OpenAI messages → (system 顶层字段, IR Messages)。

    - role=system:仅支持最多 1 条且在最前,多于 1 条或位置不对 raise
    - role=user / assistant:映射到 IR Message(block 展开见 `_user_content_to_blocks`
      / `_assistant_msg_to_ir`)
    - role=tool:作为 ToolResultBlock 前置到下一条 user;若后面无 user 或紧跟 assistant,
      单独成一条 user 消息承载 tool_results
    """
    if not msgs:
        raise ValueError("messages 不能为空")

    system: str | None = None
    start_idx = 0
    first = msgs[0]
    if isinstance(first, dict) and cast(dict[str, Any], first).get("role") == "system":
        system = _system_content_to_str(cast(dict[str, Any], first).get("content"))
        start_idx = 1

    for m in msgs[start_idx:]:
        if isinstance(m, dict) and cast(dict[str, Any], m).get("role") == "system":
            raise ValueError("role=system 只支持最多 1 条且在最前")

    result: list[Message] = []
    pending_tool_results: list[ToolResultBlock] = []

    def flush_pending() -> None:
        """把挂起的 tool_results 作为一条独立 user 消息 flush 出去。"""
        if pending_tool_results:
            result.append(Message(role="user", content=list(pending_tool_results)))
            pending_tool_results.clear()

    for raw in msgs[start_idx:]:
        if not isinstance(raw, dict):
            raise ValueError(f"message 必须是 dict,收到 {type(raw).__name__}")
        m = cast(dict[str, Any], raw)
        role = m.get("role")
        if role == "tool":
            pending_tool_results.append(_tool_msg_to_ir(m))
        elif role == "user":
            user_blocks = _user_content_to_blocks(m.get("content"))
            merged: list[ContentBlock] = [*pending_tool_results, *user_blocks]
            pending_tool_results.clear()
            if not merged:
                raise ValueError("user 消息 content 为空")
            result.append(Message(role="user", content=merged))
        elif role == "assistant":
            flush_pending()
            result.append(_assistant_msg_to_ir(m))
        else:
            raise ValueError(f"不支持的 role: {role!r}")

    flush_pending()
    return system, result


def _system_content_to_str(content: Any) -> str:
    """OpenAI system content(str 或 [{type:'text',text:...}, ...])→ 单字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in cast(list[Any], content):
            if not isinstance(part, dict):
                raise ValueError(f"system content part 必须是 dict: {part!r}")
            p = cast(dict[str, Any], part)
            if p.get("type") != "text":
                raise ValueError(f"system content 不支持的 part.type: {p.get('type')!r}")
            parts.append(str(p.get("text", "")))
        return "".join(parts)
    raise ValueError(f"system content 必须是 str 或 list,收到 {type(content).__name__}")


def _user_content_to_blocks(content: Any) -> list[ContentBlock]:
    """user content → IR ContentBlock 列表(v0.1 仅文本)。"""
    if isinstance(content, str):
        return [TextBlock(text=content)]
    if isinstance(content, list):
        blocks: list[ContentBlock] = []
        for part in cast(list[Any], content):
            if not isinstance(part, dict):
                raise ValueError(f"user content part 必须是 dict: {part!r}")
            p = cast(dict[str, Any], part)
            ptype = p.get("type")
            if ptype != "text":
                raise ValueError(f"user content 不支持的 part.type: {ptype!r}(v0.1 仅支持 text)")
            blocks.append(TextBlock(text=str(p.get("text", ""))))
        return blocks
    if content is None:
        return []
    raise ValueError(f"user content 必须是 str / list / None,收到 {type(content).__name__}")


def _tool_msg_to_ir(m: dict[str, Any]) -> ToolResultBlock:
    """OpenAI role=tool 消息 → ToolResultBlock。"""
    tc_id = m.get("tool_call_id")
    if not isinstance(tc_id, str):
        raise ValueError("role=tool 消息必须带 tool_call_id (str)")
    content = m.get("content")
    tr_content: str | list[TextBlock]
    if isinstance(content, str):
        tr_content = content
    elif isinstance(content, list):
        text_blocks: list[TextBlock] = []
        for part in cast(list[Any], content):
            if not isinstance(part, dict):
                raise ValueError(f"tool content part 必须是 dict: {part!r}")
            p = cast(dict[str, Any], part)
            if p.get("type") != "text":
                raise ValueError(f"tool content 不支持的 part.type: {p.get('type')!r}")
            text_blocks.append(TextBlock(text=str(p.get("text", ""))))
        tr_content = text_blocks
    else:
        raise ValueError(f"tool content 必须是 str 或 list,收到 {type(content).__name__}")
    return ToolResultBlock(tool_use_id=tc_id, content=tr_content)


def _assistant_msg_to_ir(m: dict[str, Any]) -> Message:
    """OpenAI role=assistant 消息 → IR Message(text block + tool_use block)。"""
    content_blocks: list[ContentBlock] = []

    content = m.get("content")
    if isinstance(content, str):
        # 空字符串也不产生 block(OpenAI 常在带 tool_calls 时把 content 设为 "" 或 None)
        if content:
            content_blocks.append(TextBlock(text=content))
    elif isinstance(content, list):
        for part in cast(list[Any], content):
            if not isinstance(part, dict):
                raise ValueError(f"assistant content part 必须是 dict: {part!r}")
            p = cast(dict[str, Any], part)
            if p.get("type") != "text":
                raise ValueError(f"assistant content 不支持的 part.type: {p.get('type')!r}")
            content_blocks.append(TextBlock(text=str(p.get("text", ""))))
    elif content is not None:
        raise ValueError(
            f"assistant content 必须是 str / list / None,收到 {type(content).__name__}"
        )

    raw_tool_calls = m.get("tool_calls")
    if raw_tool_calls:
        if not isinstance(raw_tool_calls, list):
            raise ValueError("tool_calls 必须是 list")
        for raw_tc in cast(list[Any], raw_tool_calls):
            if not isinstance(raw_tc, dict):
                raise ValueError(f"tool_call 必须是 dict: {raw_tc!r}")
            tc = cast(dict[str, Any], raw_tc)
            if tc.get("type", "function") != "function":
                raise ValueError(f"tool_call.type 必须是 function,收到 {tc.get('type')!r}")
            tc_id = tc.get("id")
            if not isinstance(tc_id, str):
                raise ValueError("tool_call.id 必须是 str")
            fn = tc.get("function")
            if not isinstance(fn, dict):
                raise ValueError("tool_call.function 必须是 dict")
            fn_d = cast(dict[str, Any], fn)
            name = fn_d.get("name")
            if not isinstance(name, str):
                raise ValueError("tool_call.function.name 必须是 str")
            args = fn_d.get("arguments", "")
            if not isinstance(args, str):
                raise ValueError("tool_call.function.arguments 必须是 str(JSON 字符串)")
            input_dict: dict[str, Any] = (
                cast(dict[str, Any], json.loads(args)) if args.strip() else {}
            )
            content_blocks.append(ToolUseBlock(id=tc_id, name=name, input=input_dict))

    if not content_blocks:
        raise ValueError("assistant 消息既无 content 也无 tool_calls")
    return Message(role="assistant", content=content_blocks)


def _tool_openai_to_ir(t: dict[str, Any]) -> dict[str, Any]:
    if t.get("type") != "function":
        raise ValueError(f"tools[].type 必须是 function,收到 {t.get('type')!r}")
    fn = t.get("function")
    if not isinstance(fn, dict):
        raise ValueError("tools[].function 必须是 dict")
    fn_d = cast(dict[str, Any], fn)
    if "strict" in fn_d:
        raise ValueError("不支持 tools[].function.strict")
    name = fn_d.get("name")
    if not isinstance(name, str):
        raise ValueError("tools[].function.name 必须是 str")
    parameters = fn_d.get("parameters", {"type": "object", "properties": {}})
    out: dict[str, Any] = {"name": name, "input_schema": parameters}
    if "description" in fn_d:
        out["description"] = fn_d["description"]
    return out


def _tool_choice_openai_to_ir(tc: Any) -> dict[str, Any]:
    if tc == "auto":
        return {"type": "auto"}
    if tc == "none":
        return {"type": "none"}
    if tc == "required":
        return {"type": "any"}
    if isinstance(tc, dict):
        tc_d = cast(dict[str, Any], tc)
        if tc_d.get("type") == "function":
            fn = tc_d.get("function")
            if not isinstance(fn, dict):
                raise ValueError("tool_choice.function 必须是 dict")
            fn_d = cast(dict[str, Any], fn)
            name = fn_d.get("name")
            if not isinstance(name, str):
                raise ValueError("tool_choice.function.name 必须是 str")
            return {"type": "tool", "name": name}
    raise ValueError(f"不支持的 tool_choice: {tc!r}")


# ---------- IR → OpenAI ----------


def ir_to_completions(ir: RequestIR) -> dict[str, Any]:
    """RequestIR → OpenAI /v1/chat/completions 请求体。"""
    if ir.top_k is not None:
        raise ValueError("OpenAI Chat Completions 不支持 top_k")
    if ir.thinking is not None:
        raise ValueError("OpenAI Chat Completions 不支持 thinking")
    if ir.metadata is not None:
        raise ValueError("OpenAI Chat Completions 不支持 metadata")

    body: dict[str, Any] = {
        "model": ir.model,
        "messages": _messages_ir_to_openai(ir.system, ir.messages),
        "max_tokens": ir.max_tokens,
    }
    if ir.temperature is not None:
        body["temperature"] = ir.temperature
    if ir.top_p is not None:
        body["top_p"] = ir.top_p
    if ir.stop_sequences:
        body["stop"] = list(ir.stop_sequences)
    if ir.stream is not None:
        body["stream"] = ir.stream
    if ir.tools is not None:
        body["tools"] = [_tool_ir_to_openai(t) for t in ir.tools]
    if ir.tool_choice is not None:
        body["tool_choice"] = _tool_choice_ir_to_openai(ir.tool_choice)
    return body


def _messages_ir_to_openai(
    system: SystemPrompt | None, messages: list[Message]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system is not None:
        if isinstance(system, str):
            out.append({"role": "system", "content": system})
        else:
            # list[TextBlock] → 合并为单字符串(OpenAI system 单条足够表达)
            merged = "".join(b.text for b in system)
            out.append({"role": "system", "content": merged})

    for msg in messages:
        if msg.role == "user":
            out.extend(_user_msg_ir_to_openai(msg))
        else:
            out.append(_assistant_msg_ir_to_openai(msg))
    return out


def _user_msg_ir_to_openai(msg: Message) -> list[dict[str, Any]]:
    """IR user 消息 → OpenAI 消息序列(tool_result blocks 拆成独立 role=tool 消息)。"""
    tool_results: list[ToolResultBlock] = []
    text_blocks: list[TextBlock] = []
    for block in msg.content:
        if isinstance(block, ToolResultBlock):
            tool_results.append(block)
        elif isinstance(block, TextBlock):
            text_blocks.append(block)
        else:
            raise ValueError(f"Chat Completions user 消息不支持的 block: {type(block).__name__}")

    out: list[dict[str, Any]] = []
    for tr in tool_results:
        if tr.is_error:
            # Chat Completions 无原生 tool error 语义;v0.1 明确 raise,避免静默丢失
            raise ValueError(
                "Chat Completions 不支持 tool_result.is_error;v0.1 不做 error-text 兜底翻译"
            )
        if isinstance(tr.content, str):
            tr_content: str | list[dict[str, Any]] = tr.content
        else:
            tr_content = [{"type": "text", "text": b.text} for b in tr.content]
        out.append(
            {
                "role": "tool",
                "tool_call_id": tr.tool_use_id,
                "content": tr_content,
            }
        )

    if text_blocks:
        if len(text_blocks) == 1:
            user_content: str | list[dict[str, Any]] = text_blocks[0].text
        else:
            user_content = [{"type": "text", "text": b.text} for b in text_blocks]
        out.append({"role": "user", "content": user_content})
    return out


def _assistant_msg_ir_to_openai(msg: Message) -> dict[str, Any]:
    text_blocks: list[TextBlock] = []
    tool_uses: list[ToolUseBlock] = []
    for block in msg.content:
        if isinstance(block, TextBlock):
            text_blocks.append(block)
        elif isinstance(block, ToolUseBlock):
            tool_uses.append(block)
        else:
            raise ValueError(
                f"Chat Completions assistant 消息不支持的 block: {type(block).__name__}"
            )

    out: dict[str, Any] = {"role": "assistant"}
    if text_blocks:
        if len(text_blocks) == 1:
            out["content"] = text_blocks[0].text
        else:
            out["content"] = [{"type": "text", "text": b.text} for b in text_blocks]
    else:
        # 带 tool_calls 但无文本时,OpenAI 惯例把 content 设 None
        out["content"] = None

    if tool_uses:
        out["tool_calls"] = [
            {
                "id": b.id,
                "type": "function",
                "function": {
                    "name": b.name,
                    "arguments": json.dumps(b.input, ensure_ascii=False),
                },
            }
            for b in tool_uses
        ]
    return out


def _tool_ir_to_openai(t: Tool) -> dict[str, Any]:
    fn: dict[str, Any] = {"name": t.name, "parameters": t.input_schema}
    if t.description is not None:
        fn["description"] = t.description
    return {"type": "function", "function": fn}


def _tool_choice_ir_to_openai(tc: ToolChoice) -> Any:
    if isinstance(tc, ToolChoiceAuto):
        return "auto"
    if isinstance(tc, ToolChoiceNone):
        return "none"
    if isinstance(tc, ToolChoiceAny):
        return "required"
    # union 穷尽:narrow 到 ToolChoiceTool
    return {"type": "function", "function": {"name": tc.name}}
