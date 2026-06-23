"""`rosetta logs` — 最近请求流水 + 实时 follow。

两种模式:
- 默认:按 `--limit` 拉最近 N 条(时间降序),打表格退出
- `--follow / -f`:先拉一批 tail(时间升序打),之后 polling(1s 间隔)增量追加;
  Ctrl+C 退出

polling 用 `list_logs(since=<last_created_at>)` 游标拉取,server 端已做 `>` 过滤,
不会重复返回本地已见过的记录。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated

import typer

from rosetta.cli.core.render import Renderer
from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.logs import LogOut

_POLL_INTERVAL_SEC = 1.0
_POLL_BATCH_LIMIT = 200
_TEXT_PREVIEW_LIMIT = 72
logs_app = typer.Typer(
    help="最近请求日志与全局日志配置",
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@logs_app.callback(invoke_without_command=True)
def logs_cmd(
    ctx: typer.Context,
    n: Annotated[int | None, typer.Option("-n", "--limit", help="最多显示多少条")] = None,
    upstream: Annotated[
        str | None, typer.Option("--upstream", help="按 upstream name 过滤")
    ] = None,
    follow: Annotated[
        bool, typer.Option("-f", "--follow", help="持续跟踪新日志(Ctrl+C 退出)")
    ] = False,
) -> None:
    """显示请求日志;默认表格打印 N 条,--follow 持续追加增量。"""
    if ctx.invoked_subcommand is not None:
        return
    try:
        asyncio.run(_run(n=n, upstream=upstream, follow=follow))
    except KeyboardInterrupt:
        Renderer.stream_newline()


@logs_app.command("config")
def config_cmd(
    log_content: Annotated[
        str | None, typer.Option("--log-content", help="none | summary | full")
    ] = None,
    page_size: Annotated[int | None, typer.Option("--page-size", help="10 | 20 | 50 | 100")] = None,
) -> None:
    try:
        asyncio.run(_config(log_content=log_content, page_size=page_size))
    except KeyboardInterrupt:
        Renderer.stream_newline()


@logs_app.command("clear")
def clear_cmd(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="确认清空全部 logs"),
    ] = False,
) -> None:
    """清空全部请求日志。"""
    if not yes:
        Renderer.die("清空全部 logs 需要显式传 --yes")
        return
    try:
        asyncio.run(_clear())
    except KeyboardInterrupt:
        Renderer.stream_newline()


async def _run(*, n: int | None, upstream: str | None, follow: bool) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            limit = n if n is not None else (await client.logs_config()).page_size
            if not follow:
                result = await client.list_logs(limit=limit, upstream=upstream)
                _print_batch(result.items, header=True)
                return
            await _follow_loop(client, upstream=upstream, tail=limit)
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")


async def _config(*, log_content: str | None, page_size: int | None) -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            cfg = (
                await client.update_logs_config(log_content=log_content, page_size=page_size)
                if log_content is not None or page_size is not None
                else await client.logs_config()
            )
            Renderer.table(
                ["key", "value"],
                [
                    ["log_content", cfg.log_content],
                    ["page_size", cfg.page_size],
                ],
            )
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")


async def _clear() -> None:
    try:
        async with ProxyClient.discover_session(spawn_if_missing=False) as client:
            deleted = await client.clear_logs()
            Renderer.out(f"cleared {deleted} log entr{'y' if deleted == 1 else 'ies'}")
    except RuntimeError as e:
        Renderer.die(f"server 未就绪: {e}")


async def _follow_loop(client: ProxyClient, *, upstream: str | None, tail: int) -> None:
    """先打 tail 批,再无限 polling since=last_created_at。"""
    initial = (await client.list_logs(limit=tail, upstream=upstream)).items
    # server 返回时间降序;follow 语义希望时间升序(新日志追加在下面)
    initial_asc = list(reversed(initial))
    _print_batch(initial_asc, header=True, follow=True)

    last_seen = initial_asc[-1].created_at if initial_asc else None
    while True:
        await asyncio.sleep(_POLL_INTERVAL_SEC)
        result = await client.list_logs(limit=_POLL_BATCH_LIMIT, upstream=upstream, since=last_seen)
        if not result.items:
            continue
        batch_asc = list(reversed(result.items))
        _print_batch(batch_asc, header=False, follow=True)
        last_seen = batch_asc[-1].created_at


def _print_batch(items: list[LogOut], *, header: bool, follow: bool = False) -> None:
    """打一批 log;follow 模式走单行格式,非 follow 走 rich table。"""
    if not items:
        if header and not follow:
            Renderer.out("no logs yet")
        return
    if follow:
        for entry in items:
            Renderer.out(_fmt_line(entry))
    else:
        Renderer.table(
            [
                "id",
                "created_at",
                "upstream",
                "model",
                "in→out",
                "ms",
                "status",
                "client_addr",
                "upstream_url",
                "request",
                "response",
            ],
            [
                [
                    entry.id[:8] + "…",
                    _fmt_time(entry.created_at),
                    entry.upstream or "-",
                    entry.model or "-",
                    f"{entry.input_tokens or 0}→{entry.output_tokens or 0}",
                    entry.latency_ms if entry.latency_ms is not None else "-",
                    entry.status,
                    entry.client_addr or "-",
                    entry.upstream_url or "-",
                    _preview(entry.request_text),
                    _preview(entry.response_text),
                ]
                for entry in items
            ],
        )


def _fmt_time(dt: datetime) -> str:
    # server 存 UTC;本地化后 ISO,和 UI 展示对齐
    return dt.astimezone().isoformat(timespec="seconds")


def _fmt_line(entry: LogOut) -> str:
    ts = _fmt_time(entry.created_at)
    status = f"{entry.status:5s}"
    up = entry.upstream or "-"
    model = entry.model or "-"
    latency = f"{entry.latency_ms}ms" if entry.latency_ms is not None else "-"
    tokens = f"{entry.input_tokens or 0}→{entry.output_tokens or 0}"
    addr = f" client={entry.client_addr}" if entry.client_addr else ""
    url = f" url={entry.upstream_url}" if entry.upstream_url else ""
    req = f" q={_preview(entry.request_text)}" if entry.request_text else ""
    ans = f" a={_preview(entry.response_text)}" if entry.response_text else ""
    tail = f" err={entry.error}" if entry.error else ""
    return (
        f"{ts} {status} upstream={up} model={model} "
        f"{latency} tokens={tokens}{addr}{url}{req}{ans}{tail}"
    )


def _preview(text: str | None) -> str:
    if not text:
        return "-"
    compact = " ".join(text.split())
    if len(compact) <= _TEXT_PREVIEW_LIMIT:
        return compact
    return compact[: _TEXT_PREVIEW_LIMIT - 1].rstrip() + "…"


def register(app: typer.Typer) -> None:
    app.add_typer(logs_app, name="logs")
