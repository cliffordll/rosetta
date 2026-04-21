"""跨格式流式事件翻译 + SSE 帧编解码(阶段 2.4)。

层次
----

`SSE bytes 流` ⇄ `dict 事件流(adapter 层)` ⇄ `IR StreamEvent 流`

- SSE 帧编解码:`parse_sse_stream`(入)/ `encode_sse_stream`(出)
  - 入:按 `\\n\\n` 切分帧,拆 `event:` / `data:` 字段,忽略注释行 / keep-alive
  - 出:按格式规则拼回(含 `event:` 行 / `data: [DONE]` 等)
- 跨格式翻译:`translate_stream`(入 SSE bytes + source/target format → 出 SSE bytes)
  内部:parse → adapter_in → IR → adapter_out → encode

错误传播(DESIGN §8.3)
----------------------
- 若 200 响应已发出(SSE 流已开始),上游中途出错:
  - 上游若发了错误事件,adapter 层能识别并转成 `ErrorEvent`,再 dump 到目标格式
  - 上游直接断连时,本模块的生成器自然抛 exception 终止,由 forwarder 捕获后
    **断 TCP 而非伪造成功事件**
- 若上游直接返回非 200(未进入流):走普通错误响应路径,不进本模块

工具调用 arguments 分片
-----------------------
当前实现:IR 的 `InputJsonDelta` 在两侧 adapter 间直接透传(不聚合)。
Anthropic 的 `partial_json` 和 OpenAI 的 `function.arguments` 分片粒度不同,但两边
SDK 都能处理任意切分——因此不必在 IR 层强制聚合。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any

from rosetta.server.translation.completions.response import (
    completions_stream_to_ir,
    ir_to_completions_stream,
)
from rosetta.server.translation.ir import StreamEvent
from rosetta.server.translation.messages.response import (
    ir_to_messages_stream,
    messages_stream_to_ir,
)
from rosetta.server.translation.responses.response import (
    ir_to_responses_stream,
    responses_stream_to_ir,
)
from rosetta.shared.formats import Format

# ---------- adapter 调度表 ----------

_STREAM_TO_IR = {
    Format.MESSAGES: messages_stream_to_ir,
    Format.CHAT_COMPLETIONS: completions_stream_to_ir,
    Format.RESPONSES: responses_stream_to_ir,
}
_IR_TO_STREAM = {
    Format.MESSAGES: ir_to_messages_stream,
    Format.CHAT_COMPLETIONS: ir_to_completions_stream,
    Format.RESPONSES: ir_to_responses_stream,
}


# ---------- SSE 帧编解码 ----------


def parse_sse_stream(raw: Iterable[bytes]) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """解码 SSE 字节流为 `(event_name, data_dict)` 序列。

    - 按 `\\n\\n` 切分帧(容忍 `\\r\\n\\r\\n`)
    - `event:` 行 → event_name;`data:` 行 → JSON 解析;注释行 `:` 忽略
    - `data: [DONE]`(OpenAI 结束 sentinel):跳过,不产生事件
    - 多个 `data:` 行按 SSE 规范拼接后再解析 JSON(v0.1 上游基本不会这样发,但兼容)
    """
    buffer = b""
    for chunk in raw:
        buffer += chunk
        while True:
            # 找下一个帧边界(\n\n 或 \r\n\r\n)
            sep_idx = -1
            sep_len = 0
            for sep in (b"\r\n\r\n", b"\n\n"):
                idx = buffer.find(sep)
                if idx != -1 and (sep_idx == -1 or idx < sep_idx):
                    sep_idx = idx
                    sep_len = len(sep)
            if sep_idx == -1:
                break
            frame = buffer[:sep_idx]
            buffer = buffer[sep_idx + sep_len :]
            parsed = _parse_frame(frame)
            if parsed is not None:
                yield parsed

    # 尾部残留按单帧再尝试解析一次(容忍结尾无空行)
    if buffer.strip():
        parsed = _parse_frame(buffer)
        if parsed is not None:
            yield parsed


def _parse_frame(frame: bytes) -> tuple[str | None, dict[str, Any]] | None:
    event_name: str | None = None
    data_lines: list[str] = []
    for raw_line in frame.split(b"\n"):
        line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
        # 其他 SSE 字段(id/retry)v0.1 不使用
    if not data_lines:
        return None
    data_str = "\n".join(data_lines)
    if data_str.strip() == "[DONE]":
        return None
    try:
        data_obj = json.loads(data_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"SSE data 不是合法 JSON: {data_str[:200]!r}") from e
    if not isinstance(data_obj, dict):
        raise ValueError(f"SSE data JSON 顶层必须是对象,收到 {type(data_obj).__name__}")
    return event_name, data_obj  # type: ignore[return-value]


def encode_sse_stream(events: Iterable[dict[str, Any]], *, format_: Format) -> Iterator[bytes]:
    """dict 事件流 → SSE 字节流。

    - Messages / Responses:每帧 `event: <type>\\ndata: <json>\\n\\n`
    - Chat Completions:每帧 `data: <json>\\n\\n`(OpenAI 没有 event: 字段);
      流末尾补 `data: [DONE]\\n\\n`
    """
    for ev in events:
        etype = ev.get("type") if isinstance(ev.get("type"), str) else None
        if format_ is Format.CHAT_COMPLETIONS:
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
        else:
            if etype:
                yield f"event: {etype}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
            else:
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()

    if format_ is Format.CHAT_COMPLETIONS:
        yield b"data: [DONE]\n\n"


# ---------- 跨格式流翻译(同步,用于单测) ----------


def translate_stream_events(
    events: Iterable[dict[str, Any]],
    *,
    source: Format,
    target: Format,
) -> Iterator[dict[str, Any]]:
    """跨格式 dict 事件流翻译:source → IR → target。"""
    ir_events: Iterator[StreamEvent] = _STREAM_TO_IR[source](events)
    yield from _IR_TO_STREAM[target](ir_events)


# ---------- 跨格式流翻译(async + 字节级) ----------


async def translate_stream_bytes(
    raw_chunks: AsyncIterable[bytes],
    *,
    source: Format,
    target: Format,
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
    for frame in encode_sse_stream(translated, format_=target):
        yield frame
