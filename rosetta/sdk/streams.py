"""SDK 侧三格式 SSE → 文本增量解码。

对 `httpx.Response`(流式)按 format 解码成文本片段迭代器;供 `chat_once` 和
CLI `chat` 流式渲染使用。与 `rosetta/server/translation/stream.py` 的 SSE 解析对称,
但这边是 **async** + 只关心文本(非流式的结构化内容不在本模块)。

两种消费方式
------------
- `iter_text_deltas(resp, fmt)`:只要文本增量,最简
- `ChatStream(fmt).text_deltas(resp)`:同样 yield 文本,但同时从终端事件累积 usage
  到实例字段(`input_tokens` / `output_tokens`),CLI 打 meta 行需要

文本抽取规则(v0.1)
--------------------
- `Protocol.MESSAGES`:`content_block_delta` + `delta.type == "text_delta"` → `delta.text`
- `Protocol.CHAT_COMPLETIONS`:`choices[0].delta.content`(chunk `data:` 行,`[DONE]` 终止)
- `Protocol.RESPONSES`:`type == "response.output_text.delta"` → `delta`(str)

Usage 抽取规则(v0.1)
---------------------
- `Protocol.MESSAGES`:`message_start.message.usage.input_tokens`(首)
  + `message_delta.usage.output_tokens`(累加式覆盖,上游会在 delta 里给累计值)
- `Protocol.CHAT_COMPLETIONS`:最后一个 chunk 的 `usage` 字段(需在请求里
  `stream_options.include_usage=true`,CLI 会自动加)
- `Protocol.RESPONSES`:`response.completed.response.usage.{input,output}_tokens`

其余事件(工具调用 / 思考 / 错误等)**忽略**——CLI 只做文本回显;更完整的事件消费
留给未来 v1+ 真正使用 ContentBlock 结构时再引入。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from rosetta.shared.protocols import Protocol


async def iter_text_deltas(resp: httpx.Response, fmt: Protocol) -> AsyncIterator[str]:
    """解码 `resp` 的 SSE 流,按 `fmt` 产出文本增量。

    调用方负责确保 `resp` 是用 `stream=True` 发出的。本函数只读不关,由外层
    async-context 管理生命周期。
    """
    async for event_name, data in _iter_sse(resp):
        text = _extract_text(fmt, event_name, data)
        if text:
            yield text


@dataclass
class ChatStream:
    """流式文本 + 终端 usage 的组合消费器。

    用法::

        stream = ChatStream(fmt=Protocol.MESSAGES)
        async for tok in stream.text_deltas(resp):
            print(tok, end="", flush=True)
        # 流结束后 stream.input_tokens / stream.output_tokens 可用
    """

    fmt: Protocol
    input_tokens: int = field(default=0)
    output_tokens: int = field(default=0)

    async def text_deltas(self, resp: httpx.Response) -> AsyncIterator[str]:
        async for event_name, data in _iter_sse(resp):
            self._update_usage(event_name, data)
            text = _extract_text(self.fmt, event_name, data)
            if text:
                yield text

    def _update_usage(self, event_name: str | None, data: dict[str, Any]) -> None:
        if self.fmt is Protocol.MESSAGES:
            etype = event_name or data.get("type")
            if etype == "message_start":
                msg = data.get("message")
                if isinstance(msg, dict):
                    u = cast(dict[str, Any], msg).get("usage")
                    if isinstance(u, dict):
                        ud = cast(dict[str, Any], u)
                        self.input_tokens = int(ud.get("input_tokens", 0) or 0)
                        # message_start 也会带 output_tokens(通常 1 或 0),用它兜底
                        self.output_tokens = int(ud.get("output_tokens", 0) or 0)
            elif etype == "message_delta":
                u = data.get("usage")
                if isinstance(u, dict):
                    ud = cast(dict[str, Any], u)
                    # Anthropic 的 message_delta.usage.output_tokens 是累计值
                    ot = ud.get("output_tokens")
                    if isinstance(ot, int):
                        self.output_tokens = ot
            return

        if self.fmt is Protocol.CHAT_COMPLETIONS:
            u = data.get("usage")
            if isinstance(u, dict):
                ud = cast(dict[str, Any], u)
                self.input_tokens = int(ud.get("prompt_tokens", 0) or 0)
                self.output_tokens = int(ud.get("completion_tokens", 0) or 0)
            return

        # Protocol.RESPONSES
        etype = event_name or data.get("type")
        if etype == "response.completed":
            resp = data.get("response")
            if isinstance(resp, dict):
                u = cast(dict[str, Any], resp).get("usage")
                if isinstance(u, dict):
                    ud = cast(dict[str, Any], u)
                    self.input_tokens = int(ud.get("input_tokens", 0) or 0)
                    self.output_tokens = int(ud.get("output_tokens", 0) or 0)


async def _iter_sse(resp: httpx.Response) -> AsyncIterator[tuple[str | None, dict[str, Any]]]:
    """异步 SSE 帧解析:按 `\\n\\n` 切分,解出 `(event_name, data_dict)`。

    - 多个 `data:` 行按 SSE 规范用 `\\n` 拼接后 JSON 解析
    - `data: [DONE]` sentinel 跳过(OpenAI 流结束标志)
    - 空帧 / 纯注释帧(以 `:` 开头)跳过
    """
    buffer = b""
    async for chunk in resp.aiter_bytes():
        buffer += chunk
        while True:
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

    # 尾部容忍无结束空行
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
    if not data_lines:
        return None
    data_str = "\n".join(data_lines)
    if data_str.strip() == "[DONE]":
        return None
    try:
        parsed = json.loads(data_str)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return event_name, cast(dict[str, Any], parsed)


def _extract_text(fmt: Protocol, event_name: str | None, data: dict[str, Any]) -> str:
    """按 format 抽文本增量;非文本事件返回空字符串。"""
    if fmt is Protocol.MESSAGES:
        etype = event_name or data.get("type")
        if etype != "content_block_delta":
            return ""
        delta = data.get("delta")
        if not isinstance(delta, dict):
            return ""
        d = cast(dict[str, Any], delta)
        if d.get("type") != "text_delta":
            return ""
        text = d.get("text", "")
        return text if isinstance(text, str) else ""

    if fmt is Protocol.CHAT_COMPLETIONS:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = cast(list[Any], choices)[0]
        if not isinstance(choice, dict):
            return ""
        delta = cast(dict[str, Any], choice).get("delta")
        if not isinstance(delta, dict):
            return ""
        content = cast(dict[str, Any], delta).get("content")
        return content if isinstance(content, str) else ""

    # Protocol.RESPONSES
    etype = event_name or data.get("type")
    if etype != "response.output_text.delta":
        return ""
    delta = data.get("delta")
    return delta if isinstance(delta, str) else ""
