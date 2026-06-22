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


# Anthropic extended thinking 中 adaptive 模式没有固定 budget,映射为 enabled 时给一个默认预算
_DEFAULT_ADAPTIVE_THINKING_BUDGET_TOKENS = 4096

# 这些字段是 Anthropic Messages 专有扩展,completions 等目标格式不支持;在 IR 入口剥离
_MESSAGES_ONLY_REQ_KEYS = frozenset({"context_management", "output_config"})


def _normalize_body(body: dict[str, Any]) -> dict[str, Any]:
    """浅复制 body,归一化 Anthropic Messages 请求入口的兼容形状。

    - `messages[i].content` 是 str 时改写成 `[{type:text,text:str}]`
    - 剥离 content block 上的 Anthropic prompt caching 扩展 `cache_control`
    - 兼容部分客户端把 `role=system` 放进 messages 的形状,归并到顶层 system
    - `thinking.type=adaptive` 映射为 `enabled` 并补默认 budget_tokens
    - 剥离 Messages 专有扩展 `context_management` / `output_config`(completions 不支持)

    ToolResultBlock.content 的 str 形式由 IR 原生 union 承接。非 dict / 非 list 的
    messages 原样交给 pydantic 报错。
    """
    normalized_body: dict[str, Any] = body
    changed = False

    # 处理 thinking.adaptive → thinking.enabled
    thinking = body.get("thinking")
    if isinstance(thinking, dict) and cast(dict[str, Any], thinking).get("type") == "adaptive":
        thinking_dict = cast(dict[str, Any], thinking)
        normalized_body = {
            **normalized_body,
            "thinking": {
                "type": "enabled",
                "budget_tokens": thinking_dict.get(
                    "budget_tokens", _DEFAULT_ADAPTIVE_THINKING_BUDGET_TOKENS
                ),
            },
        }
        changed = True

    # 剥离 Messages 专有扩展字段
    extra_keys = _MESSAGES_ONLY_REQ_KEYS & set(body.keys())
    if extra_keys:
        normalized_body = {k: v for k, v in normalized_body.items() if k not in extra_keys}
        changed = True

    if "system" in body:
        system, system_changed = _normalize_system(body.get("system"))
        if system_changed:
            normalized_body = {**normalized_body, "system": system}
            changed = True

    messages = body.get("messages")
    if not isinstance(messages, list):
        return normalized_body if changed else body

    new_messages: list[Any] = []
    system_blocks_to_append: list[dict[str, Any]] = []
    for raw_msg in cast(list[Any], messages):
        if isinstance(raw_msg, dict):
            msg = cast(dict[str, Any], raw_msg)
            content, content_changed = _normalize_message_content(msg.get("content"))
            if msg.get("role") == "system":
                system_blocks_to_append.extend(_system_content_to_text_blocks(content))
                changed = True
                continue

            if content_changed:
                new_messages.append({**msg, "content": content})
                changed = True
                continue

        new_messages.append(raw_msg)

    if system_blocks_to_append:
        normalized_body = {
            **normalized_body,
            "system": _merge_system_prompts(
                normalized_body.get("system"),
                system_blocks_to_append,
            ),
        }

    if not changed:
        return body
    return {**normalized_body, "messages": new_messages}


def _normalize_system(system: Any) -> tuple[Any, bool]:
    """剥离顶层 system text block 上的 cache_control。"""
    if isinstance(system, list):
        changed = False
        blocks: list[Any] = []
        for item in cast(list[Any], system):
            if isinstance(item, dict):
                block, block_changed = _strip_cache_control_from_block(cast(dict[str, Any], item))
                blocks.append(block)
                changed = changed or block_changed
            else:
                blocks.append(item)
        return blocks, changed
    return system, False


def _normalize_message_content(content: Any) -> tuple[Any, bool]:
    """把 str shorthand 转成 text block,并剥离 content block 的 cache_control。"""
    if isinstance(content, str):
        return [{"type": "text", "text": content}], True
    if isinstance(content, list):
        changed = False
        blocks: list[Any] = []
        for item in cast(list[Any], content):
            if isinstance(item, dict):
                block, block_changed = _strip_cache_control_from_block(cast(dict[str, Any], item))
                blocks.append(block)
                changed = changed or block_changed
            else:
                blocks.append(item)
        return blocks, changed
    return content, False


def _strip_cache_control_from_block(block: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """剥离 Anthropic prompt caching 扩展,但不递归进入 tool input 等用户数据。"""
    changed = "cache_control" in block
    new_block = {k: v for k, v in block.items() if k != "cache_control"}

    content = new_block.get("content")
    if isinstance(content, list):
        new_content: list[Any] = []
        nested_changed = False
        for item in cast(list[Any], content):
            if isinstance(item, dict):
                nested, item_changed = _strip_cache_control_from_block(cast(dict[str, Any], item))
                new_content.append(nested)
                nested_changed = nested_changed or item_changed
            else:
                new_content.append(item)
        if nested_changed:
            new_block["content"] = new_content
            changed = True

    return new_block, changed


def _system_content_to_text_blocks(content: Any) -> list[dict[str, Any]]:
    """system message content(str/list[text]) → 顶层 system text blocks。"""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        blocks: list[dict[str, Any]] = []
        for item in cast(list[Any], content):
            if not isinstance(item, dict):
                raise ValueError(f"system content part 必须是 dict: {item!r}")
            block = cast(dict[str, Any], item)
            if block.get("type") != "text":
                raise ValueError(f"system content 不支持的 part.type: {block.get('type')!r}")
            blocks.append({"type": "text", "text": str(block.get("text", ""))})
        return blocks
    raise ValueError(f"system content 必须是 str 或 list,收到 {type(content).__name__}")


def _merge_system_prompts(existing: Any, extra_blocks: list[dict[str, Any]]) -> Any:
    """把 messages 内的 system 归并到顶层 system。"""
    if existing is None:
        return extra_blocks
    if isinstance(existing, str):
        return existing + "".join(block["text"] for block in extra_blocks)
    if isinstance(existing, list):
        return [*cast(list[Any], existing), *extra_blocks]
    return existing


def ir_to_messages(ir: RequestIR) -> dict[str, Any]:
    """RequestIR → Anthropic /v1/messages 请求体。

    `exclude_none=True`:None 字段省略,避免在 body 里写出 `"system": null` 这类显式空值,
    保持与原生 SDK 发出的请求形状一致。
    """
    return ir.model_dump(mode="json", exclude_none=True)
