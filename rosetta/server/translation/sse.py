"""SSE(Server-Sent Events)字节级编解码。

职责:纯粹的 SSE 协议层 —— 字节流 ⇄ `(event_name, data_dict)` 帧。
翻译层(`dispatcher.py`)把事件 dict 送入 adapter 做 IR 翻译;SSE 本身不碰语义。

- 入:`parse_sse_stream` 按 `\\n\\n` 切分帧,拆 `event:` / `data:` 字段,忽略注释行
  和 `data: [DONE]` sentinel
- 出:`encode_sse_stream` 按格式规则拼回(Chat Completions 流末尾补 `data: [DONE]`)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator, Iterable, Iterator
from typing import Any

from rosetta.shared.protocols import Protocol


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


async def parse_sse_stream_async(
    raw: AsyncIterable[bytes],
) -> AsyncIterator[tuple[str | None, dict[str, Any]]]:
    """异步解码 SSE 字节流为 `(event_name, data_dict)` 序列。

    与 `parse_sse_stream` 语义一致,但在每个完整帧到达后立即 yield,
    避免跨格式流式翻译等待上游响应结束。
    """
    buffer = b""
    async for chunk in raw:
        buffer += chunk
        while True:
            sep_idx, sep_len = _find_frame_separator(buffer)
            if sep_idx == -1:
                break
            frame = buffer[:sep_idx]
            buffer = buffer[sep_idx + sep_len :]
            parsed = _parse_frame(frame)
            if parsed is not None:
                yield parsed

    if buffer.strip():
        parsed = _parse_frame(buffer)
        if parsed is not None:
            yield parsed


def _find_frame_separator(buffer: bytes) -> tuple[int, int]:
    """返回下一个 SSE 帧边界位置和分隔符长度;找不到返回 `(-1, 0)`。"""
    sep_idx = -1
    sep_len = 0
    for sep in (b"\r\n\r\n", b"\n\n"):
        idx = buffer.find(sep)
        if idx != -1 and (sep_idx == -1 or idx < sep_idx):
            sep_idx = idx
            sep_len = len(sep)
    return sep_idx, sep_len


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


def encode_sse_stream(events: Iterable[dict[str, Any]], *, protocol_: Protocol) -> Iterator[bytes]:
    """dict 事件流 → SSE 字节流。

    - Messages / Responses:每帧 `event: <type>\\ndata: <json>\\n\\n`
    - Chat Completions:每帧 `data: <json>\\n\\n`(OpenAI 没有 event: 字段);
      流末尾补 `data: [DONE]\\n\\n`
    """
    for ev in events:
        yield encode_sse_event(ev, protocol_=protocol_)
    if protocol_ is Protocol.CHAT_COMPLETIONS:
        yield b"data: [DONE]\n\n"


def encode_sse_event(ev: dict[str, Any], *, protocol_: Protocol) -> bytes:
    """单个 dict 事件 → 单个 SSE 帧,不追加 Chat Completions 的 `[DONE]`。"""
    etype = ev.get("type") if isinstance(ev.get("type"), str) else None
    if protocol_ is Protocol.CHAT_COMPLETIONS:
        return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
    if etype:
        return f"event: {etype}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
    return f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
