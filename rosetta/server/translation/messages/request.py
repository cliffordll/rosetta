"""Anthropic Messages API 请求体 ↔ RequestIR。

Anthropic 请求主体字段(v1):
- model / messages / system / tools / tool_choice / max_tokens
- temperature / top_p / top_k / stop_sequences / metadata
- thinking / stream

IR 形状几乎是 Anthropic 的镜像,此 adapter 做近 identity 映射 + Pydantic 强校验。
"""

from __future__ import annotations

from typing import Any

from rosetta.server.translation.ir import RequestIR


def messages_to_ir(body: dict[str, Any]) -> RequestIR:
    """Anthropic /v1/messages 请求体 → RequestIR。

    未知字段由 IR 的 extra=forbid 抛错,便于早发现未覆盖字段。
    """
    return RequestIR.model_validate(body)


def ir_to_messages(ir: RequestIR) -> dict[str, Any]:
    """RequestIR → Anthropic /v1/messages 请求体。

    `exclude_none=True`:None 字段省略,避免在 body 里写出 `"system": null` 这类显式空值,
    保持与原生 SDK 发出的请求形状一致。
    """
    return ir.model_dump(mode="json", exclude_none=True)
