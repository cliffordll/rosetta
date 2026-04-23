"""`chat_once` — 发一条消息,返回完整 `ChatResult`。

简单用例用:**非流**发出、一次性拿结果。CLI / GUI 的流式渲染另走
`ProxyClient.stream_chat` + `iter_text_deltas` 组合,不经本模块。

ChatResult 字段
--------------
- `text`:合并后的 assistant 文本(忽略 tool_use / thinking 等非文本块)
- `usage`:`{"input_tokens", "output_tokens"}`(按 format 映射上游字段)
- `path`:粗粒度路径标签(如 `"direct · api.anthropic.com"` / `"messages · server"`)
  真实的翻译链路(`messages→IR→completions` 等)在 v0.1 由 server 端日志记录,
  SDK 无法从 HTTP 响应里直接推断——留 v1+ 用 `x-rosetta-path` 响应头解决
- `latency_ms`:HTTP 往返(含 server + 上游)
- `raw_response`:原始 JSON,方便 CLI `--json` 模式直接打印
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

from rosetta.sdk.client import ProxyClient
from rosetta.shared.protocols import Protocol


@dataclass
class ChatResult:
    text: str
    usage: dict[str, int]
    path: str
    latency_ms: int
    raw_response: dict[str, Any]


async def chat_once(
    client: ProxyClient,
    text: str,
    *,
    model: str | None = None,
    fmt: Protocol = Protocol.MESSAGES,
    upstream: str | None = None,
    api_key: str | None = None,
    max_tokens: int = 1024,
) -> ChatResult:
    """发一条消息(非流式),返回 `ChatResult`。

    - `model`:None 时 direct 模式用 `client.direct_model`;server 模式必填
    - `upstream`:server 模式可选,传则作 `x-rosetta-upstream` header;direct 下禁传
    - `api_key`:server 模式可选 override;direct 下忽略(用 client 自带的)
    """
    effective_model = model
    if effective_model is None:
        effective_model = client.direct_model
    if not effective_model:
        raise ValueError("chat_once 需要指定 model(或在 direct 模式构造 client 时传入)")

    effective_fmt = fmt
    if client.direct_format is not None and client.mode == "direct":
        effective_fmt = client.direct_format

    body = _build_body(effective_fmt, text, effective_model, max_tokens)

    t0 = time.monotonic()
    resp = await client.post_chat(
        effective_fmt,
        body,
        override_api_key=api_key if client.mode == "server" else None,
        upstream_header=upstream if client.mode == "server" else None,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    resp.raise_for_status()

    data: Any = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"上游响应顶层不是对象: {type(data).__name__}")
    data_dict = cast(dict[str, Any], data)

    return ChatResult(
        text=_extract_text(effective_fmt, data_dict),
        usage=_extract_usage(effective_fmt, data_dict),
        path=_path_label(client, effective_fmt),
        latency_ms=latency_ms,
        raw_response=data_dict,
    )


def _build_body(fmt: Protocol, text: str, model: str, max_tokens: int) -> dict[str, Any]:
    if fmt is Protocol.MESSAGES:
        return {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": text}],
        }
    if fmt is Protocol.CHAT_COMPLETIONS:
        return {
            "model": model,
            "messages": [{"role": "user", "content": text}],
        }
    # Protocol.RESPONSES
    return {
        "model": model,
        "input": text,
    }


def _extract_text(fmt: Protocol, data: dict[str, Any]) -> str:
    if fmt is Protocol.MESSAGES:
        blocks = data.get("content", [])
        if not isinstance(blocks, list):
            return ""
        parts: list[str] = []
        for b in cast(list[Any], blocks):
            if isinstance(b, dict):
                bd = cast(dict[str, Any], b)
                if bd.get("type") == "text":
                    t = bd.get("text", "")
                    if isinstance(t, str):
                        parts.append(t)
        return "".join(parts)

    if fmt is Protocol.CHAT_COMPLETIONS:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = cast(list[Any], choices)[0]
        if not isinstance(first, dict):
            return ""
        msg = cast(dict[str, Any], first).get("message")
        if not isinstance(msg, dict):
            return ""
        content = cast(dict[str, Any], msg).get("content")
        return content if isinstance(content, str) else ""

    # Protocol.RESPONSES
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    parts = []
    for item in cast(list[Any], output):
        if not isinstance(item, dict):
            continue
        it = cast(dict[str, Any], item)
        if it.get("type") != "message":
            continue
        content = it.get("content")
        if not isinstance(content, list):
            continue
        for c in cast(list[Any], content):
            if isinstance(c, dict):
                cd = cast(dict[str, Any], c)
                if cd.get("type") == "output_text":
                    t = cd.get("text", "")
                    if isinstance(t, str):
                        parts.append(t)
    return "".join(parts)


def _extract_usage(fmt: Protocol, data: dict[str, Any]) -> dict[str, int]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0}
    u = cast(dict[str, Any], usage)
    if fmt is Protocol.CHAT_COMPLETIONS:
        return {
            "input_tokens": int(u.get("prompt_tokens", 0) or 0),
            "output_tokens": int(u.get("completion_tokens", 0) or 0),
        }
    # messages / responses 都用 input_tokens / output_tokens
    return {
        "input_tokens": int(u.get("input_tokens", 0) or 0),
        "output_tokens": int(u.get("output_tokens", 0) or 0),
    }


def _path_label(client: ProxyClient, fmt: Protocol) -> str:
    if client.mode == "direct":
        host = urlparse(client.base_url).hostname or client.base_url
        return f"direct · {host}"
    return f"server · {fmt.value}"
