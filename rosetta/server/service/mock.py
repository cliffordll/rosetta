"""内置 mock 上游:本地合成 echo 响应,不发真实 HTTP。

触发:`upstream.provider == "mock"` 时由 `Forwarder.forward` 短路到这里。
用途:开发 / 演示 / 离线 demo,不依赖外部 key 与网络。

架构(L3 · 全链路走 IR)
------------------------
请求侧:body → `_REQ_TO_IR[fmt]` → `RequestIR`,从 messages 里抽最后一条 user 的
TextBlock.text 作为 echo 原料。adapter 抛的 `ValidationError` / `ValueError` 统一
包成 `ServiceError(400)`,不兜底 —— "严格校验"语义。

响应侧:
- 非流:构造 `ResponseIR`(单 TextBlock + Usage),`_IR_TO_RESP[fmt](ir)` → dict → JSON
- 流式:构造 IR StreamEvent 序列(`MessageStartEvent` → N 个 `TextDeltaEvent` →
  `MessageStopEvent`),`_IR_TO_STREAM[fmt](events)` → target dict → `encode_sse_stream`
  → bytes,每帧 yield 前 `await sleep(token_delay_sec)` 控制节奏

节奏精度 vs 代码复用的权衡
---------------------------
L3 路径下 sleep 粒度是"每个 target SSE 帧",不是"每个词"。messages 协议下两者
几乎一致;completions / responses 会因 adapter 的 1:N 映射偏慢(例如 responses
的每个 IR TextDeltaEvent 会额外产 content_part 等环境帧)。人眼可感的节奏差异
很小,为此换来三协议 schema 一处维护,免去 mock 自己写 200+ 行手搓 SSE。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Iterable
from typing import Any, ClassVar, cast

from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from rosetta.server.service.exceptions import ServiceError
from rosetta.server.translation.dispatcher import (
    _IR_TO_RESP,  # pyright: ignore[reportPrivateUsage]
    _IR_TO_STREAM,  # pyright: ignore[reportPrivateUsage]
    _REQ_TO_IR,  # pyright: ignore[reportPrivateUsage]
)
from rosetta.server.translation.ir import (
    BlockStartEvent,
    BlockStopEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    RequestIR,
    ResponseIR,
    StreamEvent,
    TextBlock,
    TextDeltaEvent,
    Usage,
    UsageDelta,
)
from rosetta.server.translation.sse import encode_sse_stream
from rosetta.shared.protocols import Protocol


class MockResponder:
    """provider=mock 的本地响应生成器。全链路走 IR,adapter 保证 schema 一致。

    实例字段承载配置;模块级 `mock_responder` 单例即可直接用,测试里想加速就
    自构 `MockResponder(token_delay_sec=0)`。
    """

    _WORD_SPLIT: ClassVar[re.Pattern[str]] = re.compile(r"\S+\s*|\s+")

    def __init__(
        self,
        *,
        token_delay_sec: float = 0.02,
        echo_prefix_template: str = "[mock:{protocol}] echo: ",
        echo_limit: int = 200,
        tokens_per_char: int = 4,
    ) -> None:
        self.token_delay_sec = token_delay_sec
        self.echo_prefix_template = echo_prefix_template
        self.echo_limit = echo_limit
        self.tokens_per_char = tokens_per_char

    # ---------- 主入口 ----------

    async def respond(
        self,
        fmt: Protocol,
        body: dict[str, Any],
        *,
        stream: bool,
    ) -> Response:
        """按 fmt + stream 产出 mock 响应。body 必须是合规的 client 请求。"""
        req = self._request_to_ir(fmt, body)
        user_text = self._extract_last_user_text(req)
        reply = self._build_reply(fmt, user_text)
        input_tokens = self._estimate_tokens(user_text)
        output_tokens = self._estimate_tokens(reply)

        if not stream:
            return self._build_once_response(
                fmt, req.model, reply, input_tokens, output_tokens
            )
        return StreamingResponse(
            self._build_stream(fmt, req.model, reply, input_tokens, output_tokens),
            status_code=200,
            media_type="text/event-stream",
        )

    # ---------- 请求侧:IR 化 + 抽用户文本 ----------

    @staticmethod
    def _request_to_ir(fmt: Protocol, body: dict[str, Any]) -> RequestIR:
        """调对应 adapter 把 body 转 IR;adapter 抛的校验错包成 400。"""
        try:
            return _REQ_TO_IR[fmt](body)
        except ValidationError as e:
            raise ServiceError(
                status=400,
                code="mock_invalid_request",
                message=f"mock 请求体校验失败({fmt.value}): {e.errors()[:3]}",
            ) from e
        except ValueError as e:
            raise ServiceError(
                status=400,
                code="mock_invalid_request",
                message=f"mock 请求体校验失败({fmt.value}): {e}",
            ) from e

    @staticmethod
    def _extract_last_user_text(req: RequestIR) -> str:
        """从 IR.messages 倒序找第一条 user 消息的第一个 TextBlock;没有就空串。"""
        for msg in reversed(req.messages):
            if msg.role != "user":
                continue
            for block in msg.content:
                if isinstance(block, TextBlock):
                    return block.text
        return ""

    # ---------- reply 构造 / token 估算 / 切片 ----------

    def _build_reply(self, fmt: Protocol, user_text: str) -> str:
        """回显文本 = 前缀(含 protocol)+ 用户输入(截断);空输入显示 (empty)。"""
        prefix = self.echo_prefix_template.format(protocol=fmt.value)
        trimmed = user_text.strip()
        if len(trimmed) > self.echo_limit:
            trimmed = trimmed[: self.echo_limit] + "…"
        if not trimmed:
            return f"{prefix}(empty)"
        return f"{prefix}{trimmed}"

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // self.tokens_per_char)

    @classmethod
    def _tokenize_for_stream(cls, text: str) -> list[str]:
        """按词切,空白附前一片尾;空串返单个空片。"""
        if not text:
            return [""]
        parts = cls._WORD_SPLIT.findall(text)
        return parts or [text]

    # ---------- 非流式 ----------

    @staticmethod
    def _build_once_response(
        fmt: Protocol,
        model: str,
        reply: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Response:
        ir = ResponseIR(
            id=f"mock_{uuid.uuid4().hex[:16]}",
            model=model,
            content=[TextBlock(text=reply)],
            stop_reason="end_turn",
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        )
        body = _IR_TO_RESP[fmt](ir)
        import json

        return Response(
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            status_code=200,
            media_type="application/json",
        )

    # ---------- 流式 ----------

    async def _build_stream(
        self,
        fmt: Protocol,
        model: str,
        reply: str,
        input_tokens: int,
        output_tokens: int,
    ) -> AsyncIterator[bytes]:
        """IR 流事件 → target dict 流 → SSE bytes,每帧 sleep 一次控制节奏。"""
        ir_events = self._build_ir_events(model, reply, input_tokens, output_tokens)
        target_dicts = list(_IR_TO_STREAM[fmt](iter(ir_events)))
        for frame in encode_sse_stream(iter(target_dicts), protocol_=fmt):
            await self._sleep_tick()
            yield frame

    def _build_ir_events(
        self,
        model: str,
        reply: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Iterable[StreamEvent]:
        """构造 Anthropic 风格的 IR 事件序列;adapter 负责翻到其他 format。"""
        mid = f"mock_{uuid.uuid4().hex[:16]}"
        events: list[StreamEvent] = [
            MessageStartEvent(
                id=mid,
                model=model,
                usage=Usage(input_tokens=input_tokens, output_tokens=0),
            ),
            BlockStartEvent(index=0, block=TextBlock(text="")),
        ]
        events.extend(
            TextDeltaEvent(index=0, text=piece)
            for piece in self._tokenize_for_stream(reply)
        )
        events.append(BlockStopEvent(index=0))
        events.append(
            MessageDeltaEvent(
                stop_reason="end_turn",
                usage=UsageDelta(output_tokens=output_tokens),
            )
        )
        events.append(MessageStopEvent())
        return cast(Iterable[StreamEvent], events)

    async def _sleep_tick(self) -> None:
        # token_delay_sec=0 时跳过(测试场景加速)
        if self.token_delay_sec > 0:
            await asyncio.sleep(self.token_delay_sec)


# 模块级单例:forwarder 直接 import 使用;需定制时另构实例即可
mock_responder = MockResponder()
