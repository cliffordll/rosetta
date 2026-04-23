"""`rosetta chat` — 一次性 + REPL 流式聊天(阶段 4.3)。

两种触发
--------
- `rosetta chat "问题"`:一次性,流式打印回复 + meta 行,退出
- `rosetta chat`:进 REPL,`/help` 看命令

direct 模式(`--base-url`)留到阶段 4.4 实装,本阶段提前校验给出明确提示。
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from rosetta.cli.core.context import DEFAULT_MODELS, ChatContext
from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.shared.protocols import Protocol


def chat_cmd(
    text: Annotated[
        str | None,
        typer.Argument(help="要发送的消息;省略进入 REPL"),
    ] = None,
    protocol: Annotated[
        str, typer.Option("--protocol", help="messages | completions | responses")
    ] = "messages",
    upstream: Annotated[
        str | None,
        typer.Option("--upstream", help="指定 upstream;转成 x-rosetta-upstream 头"),
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="模型 id;未传按 protocol 取默认")
    ] = None,
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="覆盖 upstream 的 api_key")
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option("--base-url", help="direct 模式:绕 server 直连上游(阶段 4.4 接入)"),
    ] = None,
    max_tokens: Annotated[
        int, typer.Option("--max-tokens", help="messages 格式的 max_tokens")
    ] = 1024,
) -> None:
    # direct 模式占位校验,实装在 4.4
    if base_url is not None:
        Renderer.die("--base-url 在阶段 4.4 才接入;当前请去掉该参数走 server 模式")
        return

    # protocol 校验
    try:
        fmt = Protocol(protocol)
    except ValueError:
        Renderer.die(f"--protocol 必须是 messages/completions/responses,收到 {protocol!r}")
        return

    effective_model = model or DEFAULT_MODELS[fmt]

    asyncio.run(
        _run(
            text=text,
            fmt=fmt,
            model=effective_model,
            upstream=upstream,
            api_key=api_key,
            max_tokens=max_tokens,
        )
    )


async def _run(
    *,
    text: str | None,
    fmt: Protocol,
    model: str,
    upstream: str | None,
    api_key: str | None,
    max_tokens: int,
) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=True) as client:
            ctx = ChatContext(
                client=client,
                fmt=fmt,
                model=model,
                upstream=upstream,
                api_key=api_key,
                max_tokens=max_tokens,
            )
            if text is None or not text.strip():
                # 惰性 import 避开模块加载时的环路风险
                from rosetta.cli.core.repl import ChatRepl

                await ChatRepl(ctx=ctx).run()
                return

            from rosetta.cli.core.once import ChatOnce

            await ChatOnce(ctx=ctx).run(text)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")


def register(app: typer.Typer) -> None:
    app.command("chat", help="流式聊天;无参数进 REPL")(chat_cmd)
