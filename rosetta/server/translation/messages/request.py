"""Anthropic Messages API 请求体 ↔ RequestIR。

Anthropic 请求主体字段(v1):
- model / messages / system / tools / tool_choice / max_tokens
- temperature / top_p / top_k / stop_sequences / metadata
- thinking / stream

IR 形状几乎是 Anthropic 的镜像,此 adapter 做近 identity 映射 + Pydantic 强校验。
"""

from __future__ import annotations

from typing import Any, cast

from rosetta.server.translation.ir import RequestIR


def messages_to_ir(body: dict[str, Any]) -> RequestIR:
    """Anthropic /v1/messages 请求体 → RequestIR。

    未知字段由 IR 的 extra=forbid 抛错,便于早发现未覆盖字段。

    Anthropic API 允许 `message.content` 是 `str`(shorthand)或 content block 列表;
    IR 只收 list,所以这里先把 str shorthand 规范化成 `[{"type":"text","text":...}]`,
    与 completions / responses adapter 在入口做规范化的做法对称。
    """
    return RequestIR.model_validate(_normalize_body(body))


def _normalize_body(body: dict[str, Any]) -> dict[str, Any]:
    """浅复制 body,把 `messages[i].content` 是 str 的改写成 `[{type:text,text:str}]`。

    只处理顶层 message.content;ToolResultBlock.content 的 str 形式由 IR 原生 union 承接,
    不动嵌套结构。非 dict / 非 list 的 messages 原样交给 pydantic 报错。
    """
    messages = body.get("messages")
    if not isinstance(messages, list):
        return body
    new_messages: list[Any] = []
    changed = False
    for raw_msg in cast(list[Any], messages):
        if isinstance(raw_msg, dict):
            msg = cast(dict[str, Any], raw_msg)
            content = msg.get("content")
            if isinstance(content, str):
                new_messages.append({**msg, "content": [{"type": "text", "text": content}]})
                changed = True
                continue
        new_messages.append(raw_msg)
    if not changed:
        return body
    return {**body, "messages": new_messages}


def ir_to_messages(ir: RequestIR) -> dict[str, Any]:
    """RequestIR → Anthropic /v1/messages 请求体。

    `exclude_none=True`:None 字段省略,避免在 body 里写出 `"system": null` 这类显式空值,
    保持与原生 SDK 发出的请求形状一致。
    """
    return ir.model_dump(mode="json", exclude_none=True)
