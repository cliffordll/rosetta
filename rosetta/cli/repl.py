"""`rosetta chat` 的 REPL 主循环。

职责
----
- 维护 `messages: list[{"role","content"}]` 作为多轮上下文
- 读用户输入;`/` 开头分派 slash 命令,否则作为新一轮 user message
- 每轮调 `_run_turn()` 流式打印 assistant + meta 行
- slash 命令:`/exit`、`/reset`、`/model <name>`、`/format <m|c|r>`、`/help`

格式切换安全性
--------------
v0.1 REPL 只存纯文本(`content: str`),切 format 时结构无损;未来引入 tool_use /
thinking 等结构化块后,`/format` 切换需要丢弃这些块并警告(`DESIGN.md` §5.4)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rosetta.cli.commands.chat_core import DEFAULT_MODELS, ChatError, run_turn
from rosetta.cli.render import error_bubble, meta_line, out, stream_newline, stream_token
from rosetta.sdk.client import ProxyClient
from rosetta.shared.formats import Format

_PROMPT = "› "  # noqa: RUF001  特意用 U+203A 和普通 > 区分 REPL 提示符
_HELP = (
    "slash 命令:\n"
    "  /exit                    退出 REPL\n"
    "  /reset                   清空对话历史\n"
    "  /model <name>            切换模型\n"
    "  /format messages|completions|responses  切换 API 格式\n"
    "  /help                    本说明"
)


@dataclass
class ReplState:
    fmt: Format
    model: str
    provider: str | None
    api_key: str | None
    max_tokens: int
    messages: list[dict[str, str]] = field(default_factory=lambda: [])


async def run(
    client: ProxyClient,
    *,
    fmt: Format,
    model: str,
    provider: str | None,
    api_key: str | None,
    max_tokens: int,
) -> None:
    state = ReplState(
        fmt=fmt,
        model=model,
        provider=provider,
        api_key=api_key,
        max_tokens=max_tokens,
    )
    out(f"rosetta chat · format={state.fmt.value} · model={state.model} · /help 查看命令")

    while True:
        try:
            line = input(_PROMPT)
        except (EOFError, KeyboardInterrupt):
            stream_newline()
            break

        line = line.strip()
        if not line:
            continue

        if line.startswith("/"):
            if _handle_slash(state, line):
                break
            continue

        state.messages.append({"role": "user", "content": line})
        try:
            text, in_tok, out_tok, ms = await run_turn(
                client,
                state.messages,
                fmt=state.fmt,
                model=state.model,
                provider=state.provider,
                api_key=state.api_key,
                max_tokens=state.max_tokens,
                on_token=stream_token,
            )
        except ChatError as e:
            stream_newline()
            # 本轮失败,把刚加的 user 撤回,避免污染后续上下文
            state.messages.pop()
            error_bubble(f"HTTP {e.status}: {e.short_body()}")
            continue

        stream_newline()
        state.messages.append({"role": "assistant", "content": text})
        meta_line(
            provider=state.provider or "auto",
            model=state.model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=ms,
            path=state.fmt.value,
        )


def _handle_slash(state: ReplState, line: str) -> bool:
    """处理 slash 命令;返回 True 表示要退出 REPL。"""
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/exit":
        return True

    if cmd == "/help":
        out(_HELP)
        return False

    if cmd == "/reset":
        state.messages.clear()
        out("history cleared")
        return False

    if cmd == "/model":
        if not arg:
            error_bubble("用法:/model <name>")
            return False
        state.model = arg
        out(f"model → {state.model}")
        return False

    if cmd == "/format":
        try:
            new_fmt = Format(arg)
        except ValueError:
            error_bubble(f"format 必须是 messages/completions/responses,收到 {arg!r}")
            return False
        state.fmt = new_fmt
        # 切格式时如果没显式 --model,把 model 同步到新 format 的默认值
        default_for_new = DEFAULT_MODELS[new_fmt]
        if state.model in DEFAULT_MODELS.values() and state.model != default_for_new:
            state.model = default_for_new
            out(f"format → {new_fmt.value} · model → {state.model}")
        else:
            out(f"format → {new_fmt.value}")
        return False

    error_bubble(f"未知命令 {cmd!r};/help 查看可用命令")
    return False
