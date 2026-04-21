"""Anthropic Messages API 响应体 ↔ ResponseIR / StreamEvent。

非流响应:`messages_response_to_ir` / `ir_to_messages_response`。
流式响应:`messages_stream_to_ir` / `ir_to_messages_stream`。

流式 adapter 是**逐事件 1:1 映射**,不做聚合 / 缓冲 / JSON 重组。
跨格式状态机(例如把 OpenAI 的 `delta.content` 流重组成 Anthropic 风格)由阶段 2.4
的 `translation/stream.py` 接管——此 adapter 只负责"Anthropic ↔ IR"这一侧的翻译。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from pydantic import TypeAdapter

from rosetta.server.translation.ir import (
    BlockStartEvent,
    BlockStopEvent,
    ErrorEvent,
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    PingEvent,
    ResponseIR,
    SignatureDeltaEvent,
    StreamBlockStartBlock,
    StreamEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    Usage,
)

# 用于在 content_block_start 里校验 block 种子(text/thinking/redacted_thinking/tool_use 之一)
_BLOCK_ADAPTER: TypeAdapter[StreamBlockStartBlock] = TypeAdapter(StreamBlockStartBlock)


def messages_response_to_ir(body: dict[str, Any]) -> ResponseIR:
    """Anthropic /v1/messages 非流响应体 → ResponseIR。

    Anthropic 响应顶层有 `type: "message"` 字段;IR 按 role 固定 assistant、省略 type,
    解析时剥掉以避免 extra=forbid 抱怨。
    """
    payload = {k: v for k, v in body.items() if k != "type"}
    return ResponseIR.model_validate(payload)


def ir_to_messages_response(ir: ResponseIR) -> dict[str, Any]:
    """ResponseIR → Anthropic /v1/messages 非流响应体。

    补回 Anthropic 响应顶层的 `type: "message"`。
    """
    body = ir.model_dump(mode="json", exclude_none=True)
    body["type"] = "message"
    return body


# ---------- Stream ----------


def messages_stream_to_ir(events: Iterable[dict[str, Any]]) -> Iterator[StreamEvent]:
    """Anthropic SSE `data` 字典流 → IR StreamEvent 流。

    不接收原始 SSE 文本帧(`event: ...\\ndata: ...`)——那是 forwarder 的 SSE 解析层的职责;
    此 adapter 只吃已经反序列化的 JSON 对象。
    """
    for event in events:
        yield _anthropic_event_to_ir(event)


def ir_to_messages_stream(events: Iterable[StreamEvent]) -> Iterator[dict[str, Any]]:
    """IR StreamEvent 流 → Anthropic SSE `data` 字典流。"""
    for ev in events:
        yield _ir_event_to_anthropic(ev)


def _anthropic_event_to_ir(event: dict[str, Any]) -> StreamEvent:
    t = event.get("type")
    if t == "message_start":
        m = event["message"]
        return MessageStartEvent(
            id=m["id"],
            model=m["model"],
            usage=Usage.model_validate(m["usage"]),
        )
    if t == "content_block_start":
        block = _BLOCK_ADAPTER.validate_python(event["content_block"])
        return BlockStartEvent(index=event["index"], block=block)
    if t == "content_block_delta":
        return _parse_block_delta(event)
    if t == "content_block_stop":
        return BlockStopEvent(index=event["index"])
    if t == "message_delta":
        delta: dict[str, Any] = event.get("delta") or {}
        raw_usage = event.get("usage")
        return MessageDeltaEvent.model_validate(
            {
                "stop_reason": delta.get("stop_reason"),
                "stop_sequence": delta.get("stop_sequence"),
                "usage": raw_usage,
            }
        )
    if t == "message_stop":
        return MessageStopEvent()
    if t == "ping":
        return PingEvent()
    if t == "error":
        err = event["error"]
        return ErrorEvent(error_type=err["type"], message=err["message"])
    raise ValueError(f"unknown Anthropic SSE event type: {t!r}")


def _parse_block_delta(event: dict[str, Any]) -> StreamEvent:
    """把 `content_block_delta` 根据内嵌 `delta.type` 拆成具体的 IR delta 事件。"""
    delta = event["delta"]
    idx = event["index"]
    dt = delta.get("type")
    if dt == "text_delta":
        return TextDeltaEvent(index=idx, text=delta["text"])
    if dt == "thinking_delta":
        return ThinkingDeltaEvent(index=idx, thinking=delta["thinking"])
    if dt == "signature_delta":
        return SignatureDeltaEvent(index=idx, signature=delta["signature"])
    if dt == "input_json_delta":
        return InputJsonDeltaEvent(index=idx, partial_json=delta["partial_json"])
    raise ValueError(f"unknown content_block_delta type: {dt!r}")


def _ir_event_to_anthropic(ev: StreamEvent) -> dict[str, Any]:
    if isinstance(ev, MessageStartEvent):
        return {
            "type": "message_start",
            "message": {
                "id": ev.id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": ev.model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": ev.usage.model_dump(mode="json", exclude_none=True),
            },
        }
    if isinstance(ev, BlockStartEvent):
        return {
            "type": "content_block_start",
            "index": ev.index,
            "content_block": ev.block.model_dump(mode="json", exclude_none=True),
        }
    if isinstance(ev, TextDeltaEvent):
        return {
            "type": "content_block_delta",
            "index": ev.index,
            "delta": {"type": "text_delta", "text": ev.text},
        }
    if isinstance(ev, ThinkingDeltaEvent):
        return {
            "type": "content_block_delta",
            "index": ev.index,
            "delta": {"type": "thinking_delta", "thinking": ev.thinking},
        }
    if isinstance(ev, SignatureDeltaEvent):
        return {
            "type": "content_block_delta",
            "index": ev.index,
            "delta": {"type": "signature_delta", "signature": ev.signature},
        }
    if isinstance(ev, InputJsonDeltaEvent):
        return {
            "type": "content_block_delta",
            "index": ev.index,
            "delta": {"type": "input_json_delta", "partial_json": ev.partial_json},
        }
    if isinstance(ev, BlockStopEvent):
        return {"type": "content_block_stop", "index": ev.index}
    if isinstance(ev, MessageDeltaEvent):
        body: dict[str, Any] = {
            "type": "message_delta",
            "delta": {
                "stop_reason": ev.stop_reason,
                "stop_sequence": ev.stop_sequence,
            },
        }
        if ev.usage is not None:
            body["usage"] = ev.usage.model_dump(mode="json", exclude_none=True)
        return body
    if isinstance(ev, MessageStopEvent):
        return {"type": "message_stop"}
    if isinstance(ev, PingEvent):
        return {"type": "ping"}
    # 到这里 ev 必为 ErrorEvent(StreamEvent union 穷尽)
    return {"type": "error", "error": {"type": ev.error_type, "message": ev.message}}
