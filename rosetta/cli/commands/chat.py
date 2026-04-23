"""`rosetta chat` — 一次性 + REPL 流式聊天。

两种连接模式
------------
- server 模式(默认):通过本地 rosetta-server 转发;`--upstream` 指定上游,
  未给默认 `"mock"`(要求 server 侧有 name=mock 的 upstream)。
- direct 模式:`--base-url` 给上游根地址,绕过 server 直连;必须同时传
  `--api-key` + `--model`。`--base-url` 一旦给出,`--upstream` 自动失效。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
        typer.Option(
            "--upstream",
            help="server 模式的 upstream 名;未给默认 mock;--base-url 给时自动失效",
        ),
    ] = None,
    base_url: Annotated[
        str | None,
        typer.Option(
            "--base-url",
            help="direct 模式:绕 server 直连上游根地址;给出后 --upstream 自动失效",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="模型 id;server 模式按 protocol 取默认,direct 模式必填",
        ),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="server 模式覆盖 upstream 的 api_key;direct 模式必填"),
    ] = None,
    max_tokens: Annotated[
        int, typer.Option("--max-tokens", help="messages 格式的 max_tokens")
    ] = 1024,
) -> None:
    try:
        fmt = Protocol(protocol)
    except ValueError:
        Renderer.die(
            f"--protocol 必须是 messages/completions/responses,收到 {protocol!r}"
        )
        return

    if base_url is not None:
        # direct 模式:--upstream 无条件忽略;api_key / model 必填,不回退默认
        if upstream is not None:
            Renderer.err(
                f"warn: --base-url 已指定,--upstream={upstream!r} 自动失效(走 direct 模式)"
            )
        if not api_key:
            Renderer.die("--base-url 模式下 --api-key 必填")
            return
        if not model:
            Renderer.die("--base-url 模式下 --model 必填")
            return
        effective_model = model
        effective_upstream: str | None = None
    else:
        # server 模式:--upstream 缺省 mock,--model 缺省按 protocol 取
        effective_upstream = upstream or "mock"
        effective_model = model or DEFAULT_MODELS[fmt]

    asyncio.run(
        _run(
            text=text,
            fmt=fmt,
            model=effective_model,
            upstream=effective_upstream,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
        )
    )


@asynccontextmanager
async def _session(
    *,
    fmt: Protocol,
    model: str,
    api_key: str | None,
    base_url: str | None,
) -> AsyncIterator[ProxyClient]:
    """按 base_url 是否给,选 direct / server session。"""
    if base_url is not None:
        # chat_cmd 已 gate,这里 api_key 必非空
        assert api_key is not None
        async with ProxyClient.direct_session(
            base_url=base_url,
            api_key=api_key,
            format=fmt,
            model=model,
        ) as client:
            yield client
    else:
        async with ProxyClient.discover_session(spawn_if_missing=True) as client:
            yield client


async def _run(
    *,
    text: str | None,
    fmt: Protocol,
    model: str,
    upstream: str | None,
    api_key: str | None,
    base_url: str | None,
    max_tokens: int,
) -> None:
    try:
        async with _session(
            fmt=fmt, model=model, api_key=api_key, base_url=base_url
        ) as client:
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
