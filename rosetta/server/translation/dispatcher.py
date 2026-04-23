"""翻译分派器:按 (source, target) format 选择 adapter 路径。

职责
----
1. **非流式请求翻译**:client body → IR(入 adapter) → upstream body(出 adapter)
2. **非流式响应翻译**:upstream body → IR(入 adapter) → client body(出 adapter)
3. **流式事件翻译**:dict 事件流 → IR StreamEvent 流 → 目标格式事件流
4. **流式字节翻译**:SSE bytes 流 → 解码 + 翻译 + 编码 → SSE bytes 流
5. **格式一致短路**:同格式直通时 IR 过一遍再 dump,统一走 Pydantic 严格校验
   (开销极小,换所有路径的校验一致性)

SSE 字节层的编解码在 `sse.py`(`parse_sse_stream` / `encode_sse_stream`),本模块只做分派。

Protocol 枚举(沿用 `rosetta.shared.formats.Protocol`):
- `MESSAGES`:Anthropic /v1/messages
- `CHAT_COMPLETIONS`:OpenAI /v1/chat/completions
- `RESPONSES`:OpenAI /v1/responses

错误传播(DESIGN §8.3)
----------------------
- 非 200 响应(未进入流)→ 普通错误响应路径,不进本模块
- 200 响应已发出、流中途出错 → 生成器 raise 由 forwarder 断 TCP,**不伪造事件**
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any

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
from rosetta.server.translation.ir import StreamEvent
from rosetta.server.translation.messages.request import (
    ir_to_messages,
    messages_to_ir,
)
from rosetta.server.translation.messages.response import (
    ir_to_messages_response,
    ir_to_messages_stream,
    messages_response_to_ir,
    messages_stream_to_ir,
)
from rosetta.server.translation.responses.request import (
    ir_to_responses,
    responses_to_ir,
)
from rosetta.server.translation.responses.response import (
    ir_to_responses_response,
    ir_to_responses_stream,
    responses_response_to_ir,
    responses_stream_to_ir,
)
from rosetta.server.translation.sse import encode_sse_stream, parse_sse_stream
from rosetta.shared.protocols import Protocol

# Adapter 表:按方向 x 消息类型 共 6 张

_REQ_TO_IR = {
    Protocol.MESSAGES: messages_to_ir,
    Protocol.CHAT_COMPLETIONS: completions_to_ir,
    Protocol.RESPONSES: responses_to_ir,
}
_IR_TO_REQ = {
    Protocol.MESSAGES: ir_to_messages,
    Protocol.CHAT_COMPLETIONS: ir_to_completions,
    Protocol.RESPONSES: ir_to_responses,
}
_RESP_TO_IR = {
    Protocol.MESSAGES: messages_response_to_ir,
    Protocol.CHAT_COMPLETIONS: completions_response_to_ir,
    Protocol.RESPONSES: responses_response_to_ir,
}
_IR_TO_RESP = {
    Protocol.MESSAGES: ir_to_messages_response,
    Protocol.CHAT_COMPLETIONS: ir_to_completions_response,
    Protocol.RESPONSES: ir_to_responses_response,
}
_STREAM_TO_IR = {
    Protocol.MESSAGES: messages_stream_to_ir,
    Protocol.CHAT_COMPLETIONS: completions_stream_to_ir,
    Protocol.RESPONSES: responses_stream_to_ir,
}
_IR_TO_STREAM = {
    Protocol.MESSAGES: ir_to_messages_stream,
    Protocol.CHAT_COMPLETIONS: ir_to_completions_stream,
    Protocol.RESPONSES: ir_to_responses_stream,
}


# ---------- 非流式 ----------


def translate_request(
    body: dict[str, Any], *, source: Protocol, target: Protocol
) -> dict[str, Any]:
    """客户端请求 body → 上游请求 body。

    `source == target` 时仍走 IR,作为统一校验通道。
    """
    ir = _REQ_TO_IR[source](body)
    return _IR_TO_REQ[target](ir)


def translate_response(
    body: dict[str, Any], *, source: Protocol, target: Protocol
) -> dict[str, Any]:
    """上游响应 body → 客户端响应 body。

    `source` 是上游的 format,`target` 是客户端的 format。
    """
    ir = _RESP_TO_IR[source](body)
    return _IR_TO_RESP[target](ir)


# ---------- 流式 ----------


def translate_stream_events(
    events: Iterable[dict[str, Any]],
    *,
    source: Protocol,
    target: Protocol,
) -> Iterator[dict[str, Any]]:
    """跨格式 dict 事件流翻译:source → IR → target。

    单测 + 编排用;字节级 SSE 翻译走 `translate_stream_bytes`。
    """
    ir_events: Iterator[StreamEvent] = _STREAM_TO_IR[source](events)
    yield from _IR_TO_STREAM[target](ir_events)


async def translate_stream_bytes(
    raw_chunks: AsyncIterable[bytes],
    *,
    source: Protocol,
    target: Protocol,
) -> AsyncIterator[bytes]:
    """上游 SSE 字节流 → 客户端 SSE 字节流(完整翻译链)。

    - source == target 时仍走 adapter 管道做强校验,代价是一次 JSON 解析 + dump;
      若未来证明性能敏感再加同格式短路
    - 生成器中途抛异常(上游断连 / 解析失败)由调用方捕获:已发 200 的情况下应断 TCP,
      不追加伪造事件
    """
    # 将 async bytes 聚合成同步可迭代(简单实现:内存缓冲按帧 yield)
    # 真正低延迟的实现要把 SSE 解析做成 async 生成器;v0.1 先以正确为先,后续按需优化
    collected: list[bytes] = []
    async for chunk in raw_chunks:
        collected.append(chunk)

    parsed_events = (event_dict for _name, event_dict in parse_sse_stream(iter(collected)))
    translated = translate_stream_events(parsed_events, source=source, target=target)
    for frame in encode_sse_stream(translated, protocol_=target):
        yield frame
