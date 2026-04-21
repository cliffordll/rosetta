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

from rosetta.cli.commands.chat_core import DEFAULT_MODELS, ChatError, run_turn
from rosetta.cli.render import die, error_bubble, meta_line, stream_newline, stream_token
from rosetta.sdk.client import ProxyClient
from rosetta.shared.formats import Format


def chat_cmd(
    text: Annotated[
        str | None,
        typer.Argument(help="要发送的消息;省略进入 REPL"),
    ] = None,
    format: Annotated[
        str, typer.Option("--format", help="messages | completions | responses")
    ] = "messages",
    model: Annotated[
        str | None, typer.Option("--model", help="模型 id;未传按 format 取默认")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", help="指定 provider(绕路由);转成 x-rosetta-provider 头"),
    ] = None,
    api_key: Annotated[
        str | None, typer.Option("--api-key", help="覆盖 provider 的 api_key")
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
        die("--base-url 在阶段 4.4 才接入;当前请去掉该参数走 server 模式")
        return

    # format 校验
    try:
        fmt = Format(format)
    except ValueError:
        die(f"--format 必须是 messages/completions/responses,收到 {format!r}")
        return

    effective_model = model or DEFAULT_MODELS[fmt]

    asyncio.run(
        _run(
            text=text,
            fmt=fmt,
            model=effective_model,
            provider=provider,
            api_key=api_key,
            max_tokens=max_tokens,
        )
    )


async def _run(
    *,
    text: str | None,
    fmt: Format,
    model: str,
    provider: str | None,
    api_key: str | None,
    max_tokens: int,
) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=True) as client:
            if text is None or not text.strip():
                # 惰性 import 避开模块加载时的环路风险
                from rosetta.cli import repl as repl_mod

                await repl_mod.run(
                    client,
                    fmt=fmt,
                    model=model,
                    provider=provider,
                    api_key=api_key,
                    max_tokens=max_tokens,
                )
                return

            await _one_shot(
                client,
                text=text,
                fmt=fmt,
                model=model,
                provider=provider,
                api_key=api_key,
                max_tokens=max_tokens,
            )
    except RuntimeError as e:
        die(f"server 未就绪: {e}")


async def _one_shot(
    client: ProxyClient,
    *,
    text: str,
    fmt: Format,
    model: str,
    provider: str | None,
    api_key: str | None,
    max_tokens: int,
) -> None:
    messages = [{"role": "user", "content": text}]
    try:
        _assistant, in_tok, out_tok, ms = await run_turn(
            client,
            messages,
            fmt=fmt,
            model=model,
            provider=provider,
            api_key=api_key,
            max_tokens=max_tokens,
            on_token=stream_token,
        )
    except ChatError as e:
        stream_newline()
        error_bubble(f"HTTP {e.status}: {e.short_body()}")
        raise typer.Exit(code=1) from None

    stream_newline()
    meta_line(
        provider=provider or "auto",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=ms,
        path=fmt.value,
    )


def register(app: typer.Typer) -> None:
    app.command("chat", help="流式聊天;无参数进 REPL")(chat_cmd)
