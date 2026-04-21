"""`chat` 命令与 REPL 的共用核心:一轮流式请求 + usage 抽取。

独立于 typer,方便一次性命令和 REPL 复用。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rosetta.sdk.client import ProxyClient
from rosetta.sdk.streams import ChatStream
from rosetta.shared.formats import Format

DEFAULT_MODELS: dict[Format, str] = {
    Format.MESSAGES: "claude-haiku-4-5",
    Format.CHAT_COMPLETIONS: "gpt-4o-mini",
    Format.RESPONSES: "gpt-4o-mini",
}


@dataclass
class ChatError(Exception):
    status: int
    body: str

    def short_body(self, limit: int = 200) -> str:
        s = self.body.strip()
        return s if len(s) <= limit else s[:limit] + "…"


async def run_turn(
    client: ProxyClient,
    messages: list[dict[str, str]],
    *,
    fmt: Format,
    model: str,
    provider: str | None,
    api_key: str | None,
    max_tokens: int,
    on_token: Callable[[str], None],
) -> tuple[str, int, int, int]:
    """发一轮(流式),`on_token` 实时收每个文本增量。

    返回 `(assistant_text, input_tokens, output_tokens, latency_ms)`;上游 4xx/5xx
    时抛 `ChatError`(body 为响应正文)。
    """
    body = _build_body(fmt, messages, model, max_tokens)
    stream = ChatStream(fmt=fmt)
    buf: list[str] = []
    t0 = time.monotonic()

    async with client.stream_chat(
        fmt,
        body,
        override_api_key=api_key if client.mode == "server" else None,
        provider_header=provider if client.mode == "server" else None,
    ) as resp:
        if resp.status_code >= 400:
            err_bytes = await resp.aread()
            raise ChatError(
                status=resp.status_code,
                body=err_bytes.decode("utf-8", errors="replace"),
            )
        async for tok in stream.text_deltas(resp):
            on_token(tok)
            buf.append(tok)

    latency_ms = int((time.monotonic() - t0) * 1000)
    return "".join(buf), stream.input_tokens, stream.output_tokens, latency_ms


def _build_body(
    fmt: Format,
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    """按 format 把对话历史组装成请求体。

    v0.1 只存纯文本(`content: str`),三格式的多轮表达都能直接消化。
    """
    if fmt is Format.MESSAGES:
        return {
            "model": model,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": messages,
        }

    if fmt is Format.CHAT_COMPLETIONS:
        # include_usage=true 才能让最后一个 chunk 带 prompt/completion_tokens
        return {
            "model": model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "messages": messages,
        }

    # Format.RESPONSES
    return {
        "model": model,
        "stream": True,
        "input": [{"role": m["role"], "content": m["content"]} for m in messages],
    }
