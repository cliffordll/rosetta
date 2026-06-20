"""`rosetta chat "问题"` — 一次性模式执行器。

`ChatOnce` 持有 `ChatContext`,跑一轮请求 + 打印 meta 行。与 `ChatRepl` 对称,
都是"`ChatContext` 上的一种执行模式"。典型 caller 是 CLI 命令 `commands/chat.py`。
"""

from __future__ import annotations

from dataclasses import dataclass

import typer

from rosetta.cli.core.context import ChatContext, ChatError
from rosetta.cli.core.render import Renderer
from rosetta.sdk.raw import RawChatTurn, format_raw_turn


@dataclass
class ChatOnce:
    """一次性聊天执行器:发一条消息 + 流式打印 + meta 行;失败 `typer.Exit(1)`。"""

    ctx: ChatContext
    raw: bool = False
    raw_edge: int = 10
    raw_step: int = 10
    raw_full: bool = False

    async def run(self, text: str) -> None:
        self.ctx.append_user(text)
        raw_turn = RawChatTurn() if self.raw else None
        try:
            result = await self.ctx.run_turn(
                _noop if self.raw else Renderer.stream_token,
                raw_turn=raw_turn,
            )
        except ChatError as e:
            if raw_turn is not None:
                Renderer.raw(
                    format_raw_turn(
                        raw_turn,
                        edge_frames=self.raw_edge,
                        revealed_middle_frames=0,
                        full=self.raw_full,
                    )
                )
            else:
                Renderer.stream_newline()
            Renderer.error_bubble(f"HTTP {e.status}: {e.short_body()}")
            raise typer.Exit(code=1) from None

        if raw_turn is not None:
            Renderer.raw(
                format_raw_turn(
                    raw_turn,
                    edge_frames=self.raw_edge,
                    revealed_middle_frames=0,
                    full=self.raw_full,
                )
            )
            return

        Renderer.stream_newline()
        Renderer.meta_line(
            upstream=self.ctx.upstream or "auto",
            model=self.ctx.model or "auto",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            path=self.ctx.server_api.value,
        )


def _noop(_: str) -> None:
    pass
