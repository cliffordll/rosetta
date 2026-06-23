"""chat 会话上下文:客户端 + 会话配置 + 多轮 messages 历史。

`ChatContext` 同时服务一次性命令(`chat.py::_one_shot`)和 REPL(`repl.py`)。
独立于 typer / REPL / 前端 UI,只管"一轮流式请求 + usage 抽取 + 消息历史"。

典型用法
--------
```
# model=None 时不发 body.model,server 用 upstream.model 兜底
ctx = ChatContext(client=client, server_api=ServerApi.MESSAGES, model=None)
ctx.append_user("hi")
result = await ctx.run_turn(on_token=print)
ctx.append_assistant(result.text)
```
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from rosetta.sdk.client import ProxyClient
from rosetta.sdk.raw import RawChatError, RawChatRequest, RawChatResponse, RawChatTurn
from rosetta.sdk.streams import ChatStream
from rosetta.shared.server_api import ServerApi


def _empty_messages() -> list[dict[str, str]]:
    """messages 字段的 default_factory;helper 函数显式标注类型避免 pyright 报 Unknown。"""
    return []


@dataclass
class ChatError(Exception):
    """上游 4xx / 5xx 时 run_turn 抛出的异常,body 为响应正文。"""

    status: int
    body: str

    def short_body(self, limit: int = 200) -> str:
        s = self.body.strip()
        return s if len(s) <= limit else s[:limit] + "…"


@dataclass(frozen=True)
class TurnResult:
    """一轮流式请求的收尾结果(替代原 tuple[str, int, int, int] 返回)。"""

    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass
class ChatContext:
    """一次聊天会话的完整上下文:客户端 + 会话配置 + 多轮历史。

    `model: str | None`:None 时 `_build_body` 不发 `model` 字段,server forwarder
    用 `upstream.model` 兜底(与 `api_key` 留空透传 upstream.api_key 的语义对齐)。
    """

    client: ProxyClient
    server_api: ServerApi
    model: str | None
    upstream: str | None = None
    api_key: str | None = None
    max_tokens: int = 1024
    stream: bool = True
    messages: list[dict[str, str]] = field(default_factory=_empty_messages)

    # ---------- 状态操作 ----------

    def append_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def append_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def pop_last(self) -> None:
        """撤回最后一条消息;REPL 本轮请求失败时用,避免污染后续上下文。"""
        if self.messages:
            self.messages.pop()

    def reset(self) -> None:
        """清空对话历史,保留会话配置(server_api / model / upstream ...)。"""
        self.messages.clear()

    def set_server_api(self, server_api: ServerApi) -> None:
        self.server_api = server_api

    def set_model(self, model: str | None) -> None:
        self.model = model

    def set_upstream(self, upstream: str | None) -> None:
        self.upstream = upstream

    def set_api_key(self, api_key: str | None) -> None:
        self.api_key = api_key

    def set_stream(self, stream: bool) -> None:
        self.stream = stream

    def set_max_tokens(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens

    # ---------- 核心:一轮请求 ----------

    async def run_turn(
        self,
        on_token: Callable[[str], None],
        *,
        raw_turn: RawChatTurn | None = None,
    ) -> TurnResult:
        """用当前 `self.messages` 发一轮请求。`self.stream=True` 时流式逐 token 输出,
        `self.stream=False` 时等待完整响应后一次性调用 `on_token` 输出全文。

        上游 4xx / 5xx 时抛 `ChatError`(body = 响应正文)。
        `direct` 模式下 api_key / upstream header 不走 server 透传路径。
        """
        body = self._build_body()
        t0 = time.monotonic()
        override_api_key = self.api_key if self.client.mode == "server" else None
        upstream_header = self.upstream if self.client.mode == "server" else None

        if not self.stream:
            return await self._run_non_stream(
                body, on_token, raw_turn=raw_turn,
                override_api_key=override_api_key, upstream_header=upstream_header, t0=t0,
            )

        stream = ChatStream(server_api=self.server_api)
        buf: list[str] = []
        raw_response: RawChatResponse | None = None

        if raw_turn is not None:
            url, headers = self.client.data_url_and_headers(
                self.server_api,
                override_api_key=override_api_key,
                upstream_header=upstream_header,
            )
            raw_turn.request = RawChatRequest(url=url, headers=headers, body=body)
            raw_response = RawChatResponse(frames=[])
            raw_turn.response = raw_response

        async with self.client.stream_chat(
            self.server_api,
            body,
            override_api_key=override_api_key,
            upstream_header=upstream_header,
        ) as resp:
            if resp.status_code >= 400:
                err_bytes = await resp.aread()
                if raw_turn is not None:
                    raw_turn.response = RawChatResponse(
                        frames=[],
                        error=RawChatError(
                            status=resp.status_code,
                            body=err_bytes.decode("utf-8", errors="replace"),
                        ),
                    )
                raise ChatError(
                    status=resp.status_code,
                    body=err_bytes.decode("utf-8", errors="replace"),
                )
            async for tok in stream.text_deltas(
                resp,
                on_frame=raw_response.frames.append if raw_response is not None else None,
            ):
                on_token(tok)
                buf.append(tok)

        return TurnResult(
            text="".join(buf),
            input_tokens=stream.input_tokens,
            output_tokens=stream.output_tokens,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def _run_non_stream(
        self,
        body: dict[str, Any],
        on_token: Callable[[str], None],
        *,
        raw_turn: RawChatTurn | None = None,
        override_api_key: str | None,
        upstream_header: str | None,
        t0: float,
    ) -> TurnResult:
        resp = await self.client.post_chat(
            self.server_api,
            body,
            override_api_key=override_api_key,
            upstream_header=upstream_header,
        )
        if resp.status_code >= 400:
            raise ChatError(
                status=resp.status_code,
                body=resp.text,
            )
        data = resp.json()
        full_text = _extract_non_stream_text(data, self.server_api)
        on_token(full_text)

        if raw_turn is not None:
            url, headers = self.client.data_url_and_headers(
                self.server_api,
                override_api_key=override_api_key,
                upstream_header=upstream_header,
            )
            raw_turn.request = RawChatRequest(url=url, headers=headers, body=body)
            raw_turn.response = RawChatResponse(
                frames=[],
                error=None,
            )

        return TurnResult(
            text=full_text,
            input_tokens=_extract_input_tokens(data, self.server_api),
            output_tokens=_extract_output_tokens(data, self.server_api),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    # ---------- 私有:按 server_api 组装请求体 ----------

    def _build_body(self) -> dict[str, Any]:
        """按 self.server_api 把对话历史组装成请求体。

        v0.1 只存纯文本(`content: str`),三格式的多轮表达都能直接消化。
        `self.model is None` 时 body 不写 `model` 字段,让 server forwarder 走
        upstream.model 兜底。
        """
        # model 字段:None 时不写;放在 body 头便于阅读
        model_field: dict[str, Any] = {"model": self.model} if self.model else {}

        if self.server_api is ServerApi.MESSAGES:
            return {
                **model_field,
                "max_tokens": self.max_tokens,
                "stream": self.stream,
                "messages": self.messages,
            }

        if self.server_api is ServerApi.CHAT_COMPLETIONS:
            # include_usage=true 让最后一个 chunk 带 prompt/completion_tokens
            # max_tokens 按 messages 语义复用一个值;真实 OpenAI 可不传,但 rosetta
            # 的翻译层 adapter 要求必填,一次性给齐简化下游路径
            return {
                **model_field,
                "stream": self.stream,
                "stream_options": {"include_usage": True} if self.stream else {},
                "max_tokens": self.max_tokens,
                "messages": self.messages,
            }

        # ServerApi.RESPONSES:字段名是 max_output_tokens,语义同 max_tokens;
        # input item 按 Responses 规范带 type="message"(否则 adapter 拒)
        return {
            **model_field,
            "stream": self.stream,
            "max_output_tokens": self.max_tokens,
            "input": [
                {"type": "message", "role": m["role"], "content": m["content"]}
                for m in self.messages
            ],
        }



def _extract_non_stream_text(data: dict[str, Any], server_api: ServerApi) -> str:
    if server_api is ServerApi.MESSAGES:
        blocks = data.get("content", [])
        if isinstance(blocks, list):
            parts: list[str] = []
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = b.get("text", "")
                    if isinstance(t, str):
                        parts.append(t)
            return "".join(parts)
        return ""
    if server_api is ServerApi.CHAT_COMPLETIONS:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                content = msg.get("content")
                return content if isinstance(content, str) else ""
        return ""
    output = data.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "output_text":
                            t = c.get("text", "")
                            if isinstance(t, str):
                                parts.append(t)
        return "".join(parts)
    return ""


def _extract_input_tokens(data: dict[str, Any], server_api: ServerApi) -> int:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0
    if server_api is ServerApi.MESSAGES:
        return usage.get("input_tokens", 0) or 0
    if server_api is ServerApi.CHAT_COMPLETIONS:
        return usage.get("prompt_tokens", 0) or 0
    return 0


def _extract_output_tokens(data: dict[str, Any], server_api: ServerApi) -> int:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0
    if server_api is ServerApi.MESSAGES:
        return usage.get("output_tokens", 0) or 0
    if server_api is ServerApi.CHAT_COMPLETIONS:
        return usage.get("completion_tokens", 0) or 0
    return 0
