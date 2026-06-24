"""`rosetta chat` — 一次性 + REPL 流式聊天。

两种连接模式
------------
- server 模式(默认):通过本地 rosetta-server 转发;`--upstream` 指定上游,
  未给则不传 `r-upstream` header,server 按 body.model 匹配 upstream;同 model
  多 upstream 时用 `rosetta upstream default --model ...` 指定默认。
  `--model` 同样可选,留空时不发 `body.model`,server forwarder 用 `upstream.model`
  兜底(与 `--api-key` 行为对称)。
- direct 模式:`--base-url` 给上游根地址,绕过 server 直连;必须同时传
  `--api-key` + `--model`。`--base-url` 一旦给出,`--upstream` 自动失效。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

import typer

from rosetta.cli.core.context import ChatContext
from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.shared.server_api import ServerApi


def chat_cmd(
    text: Annotated[
        str | None,
        typer.Argument(help="要发送的消息;省略进入 REPL"),
    ] = None,
    server_api_value: Annotated[
        str,
        typer.Option(
            "--server-api",
            help=(
                "server_api: messages(/v1/messages) | "
                "completions(/v1/chat/completions) | responses(/v1/responses)"
            ),
        ),
    ] = "messages",
    upstream: Annotated[
        str | None,
        typer.Option(
            "--upstream",
            help="server 模式 upstream 名;未给则 server 按 model 匹配;--base-url 给时失效",
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
            help="模型 id;server 模式可留空(走 upstream.model 兜底),direct 模式必填",
        ),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="server 模式覆盖 upstream 的 api_key;direct 模式必填"),
    ] = None,
    max_tokens: Annotated[
        int, typer.Option("--max-tokens", help="messages 格式的 max_tokens")
    ] = 8192,
    stream: Annotated[
        bool | None,
        typer.Option(
            "--stream/--no-stream", help="流式逐 token 输出;非流式等待完整响应后一次性输出"
        ),
    ] = None,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="输出原始 request 和 SSE response,不做 nice 文本渲染"),
    ] = False,
    raw_edge: Annotated[
        int,
        typer.Option("--raw-edge", min=1, help="raw response 默认显示前/后多少条 SSE frame"),
    ] = 5,
    raw_step: Annotated[
        int,
        typer.Option("--raw-step", min=1, help="保留参数:CLI 当前不交互展开;完整输出用 --raw-full"),
    ] = 10,
    raw_full: Annotated[
        bool,
        typer.Option("--raw-full", help="raw response 输出完整 SSE frame,不隐藏中间数据"),
    ] = False,
) -> None:
    try:
        server_api = ServerApi(server_api_value)
    except ValueError:
        Renderer.die(
            f"--server-api 必须是 messages/completions/responses,收到 {server_api_value!r}"
        )
        return

    # 规范 sentinel 值: --api-key="none"/"" / --model="none"/"" 统一转 None,
    # 让 server 用 upstream.api_key / upstream.model 兜底,与 Web UI 的空 = 用默认行为对齐。
    if api_key and api_key.strip().lower() in ("none", ""):
        api_key = None
    if model and model.strip().lower() in ("none", ""):
        model = None

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
        effective_model: str | None = model
        effective_upstream: str | None = None
    else:
        # server 模式:--upstream / --model 都不缺省;None 让 server 按数据面规则处理
        effective_upstream = upstream
        effective_model = model

    asyncio.run(
        _run(
            text=text,
            server_api=server_api,
            model=effective_model,
            upstream=effective_upstream,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
            stream=stream,
            raw=raw,
            raw_edge=raw_edge,
            raw_step=raw_step,
            raw_full=raw_full,
        )
    )


@asynccontextmanager
async def _session(
    *,
    server_api: ServerApi,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> AsyncGenerator[ProxyClient]:
    """按 base_url 是否给,选 direct / server session。"""
    if base_url is not None:
        # chat_cmd 已 gate,这里 api_key / model 必非空
        assert api_key is not None
        assert model is not None
        async with ProxyClient.direct_session(
            base_url=base_url,
            api_key=api_key,
            server_api=server_api,
            model=model,
        ) as client:
            yield client
    else:
        async with ProxyClient.discover_session(spawn_if_missing=True) as client:
            yield client


async def _run(
    *,
    text: str | None,
    server_api: ServerApi,
    model: str | None,
    upstream: str | None,
    api_key: str | None,
    base_url: str | None,
    max_tokens: int,
    stream: bool | None = None,
    raw: bool,
    raw_edge: int,
    raw_step: int,
    raw_full: bool,
) -> None:
    try:
        async with _session(
            server_api=server_api, model=model, api_key=api_key, base_url=base_url
        ) as client:
            # server 模式:从 settings 表加载 chat 配置,CLI 参数优先
            if base_url is None and client.mode == "server":
                try:
                    cfg = await client.chat_config()
                    _max_tokens = max_tokens if max_tokens != 8192 else cfg.max_tokens
                    _stream = cfg.stream if stream is None else stream
                except Exception:
                    _max_tokens = max_tokens
                    _stream = True if stream is None else stream
            else:
                _max_tokens = max_tokens
                _stream = True if stream is None else stream
            ctx = ChatContext(
                client=client,
                server_api=server_api,
                model=model,
                upstream=upstream,
                api_key=api_key,
                max_tokens=_max_tokens,
                stream=_stream,
            )
            if text is None or not text.strip():
                # 惰性 import 避开模块加载时的环路风险
                from rosetta.cli.core.repl import ChatRepl

                await ChatRepl(
                    ctx=ctx,
                    raw=raw,
                    raw_edge=raw_edge,
                    raw_step=raw_step,
                    raw_full=raw_full,
                ).run()
                return

            from rosetta.cli.core.once import ChatOnce

            await ChatOnce(
                ctx=ctx,
                raw=raw,
                raw_edge=raw_edge,
                raw_step=raw_step,
                raw_full=raw_full,
            ).run(text)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")


def register(app: typer.Typer) -> None:
    app.command("chat", help="流式聊天;无参数进 REPL")(chat_cmd)
