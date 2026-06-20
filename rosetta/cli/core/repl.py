"""`rosetta chat` 的终端 REPL 循环。

`ChatRepl` 实例类持有 `ChatContext`,职责:
- 读用户输入(`input()`)
- `/` 开头分派 slash 命令,否则作为新一轮 user message
- 每轮调 `ctx.run_turn()` 流式打印 assistant + meta 行
- slash 命令:`/exit`(`/quit` 别名) / `/reset` / `/model <name>` /
  `/server_api <api_type>` / `/raw on|off` / `/raw_edge <n>` / `/raw_step <n>` / `/help`

状态持有
--------
会话状态(server_api / model / upstream / api_key / max_tokens / messages)全部
在 `ChatContext` 实例里。本类只负责"输入分派 + 打印"。

格式切换安全性
--------------
v0.1 REPL 只存纯文本(`content: str`),切 server_api 时结构无损;未来引入 tool_use /
thinking 等结构化块后,`/server_api` 切换需要丢弃这些块并警告(`DESIGN.md` §5.4)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from rosetta.cli.core.context import ChatContext, ChatError
from rosetta.cli.core.prompt import ReplInput, make_repl_input
from rosetta.cli.core.render import Renderer
from rosetta.sdk.raw import RawChatTurn, format_raw_turn
from rosetta.shared.server_api import ServerApi


@dataclass
class ChatRepl:
    """终端 REPL 会话。持有一个 `ChatContext`,循环读输入并分派命令。"""

    ctx: ChatContext
    raw: bool = False
    raw_edge: int = 5
    raw_step: int = 10
    raw_full: bool = False
    input_reader: ReplInput = field(default_factory=make_repl_input)

    # U+203A 单右尖引号,和普通 > 视觉上有区别,便于识别 REPL 提示符
    _PROMPT: ClassVar[str] = "› "  # noqa: RUF001

    _HELP: ClassVar[str] = (
        "slash 命令:\n"
        "  /exit, /quit              退出 REPL\n"
        "  /reset                    清空对话历史\n"
        "  /model <name|clear>       显示/切换模型;clear = auto\n"
        "  /server_api <api_type>    切换 API 格式(messages|completions|responses)\n"
        "  /raw on|off               切换 raw request/response 输出\n"
        "  /raw_edge <n>             raw 模式显示前/后 n 条 SSE frame\n"
        "  /raw_step <n>             raw 模式每次展开 n 条 SSE frame\n"
        "  /help                     本说明"
    )

    async def run(self) -> None:
        """主循环:读输入 → 分派 slash / 发请求 → 打印 meta 行。

        Ctrl+C / EOF / `/exit` / `/quit` 退出。
        """
        Renderer.out(
            f"rosetta chat · server_api={self.ctx.server_api.value} · "
            f"model={self.ctx.model or 'auto'} · "
            f"mode={'raw' if self.raw else 'nice'} · /help 查看命令"
        )

        while True:
            try:
                line = await self.input_reader.read(self._PROMPT)
            except (EOFError, KeyboardInterrupt):
                Renderer.stream_newline()
                return

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                if self._handle_slash(line):
                    return
                continue

            await self._one_turn(line)

    async def _one_turn(self, user_text: str) -> None:
        """发一轮请求;失败撤回 user,避免污染后续上下文。"""
        self.ctx.append_user(user_text)
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
            self.ctx.pop_last()
            Renderer.error_bubble(f"HTTP {e.status}: {e.short_body()}")
            return

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
        self.ctx.append_assistant(result.text)
        Renderer.meta_line(
            upstream=self.ctx.upstream or "auto",
            model=self.ctx.model or "auto",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            path=self.ctx.server_api.value,
        )

    def _handle_slash(self, line: str) -> bool:
        """处理 slash 命令;返回 True 表示要退出 REPL。"""
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/exit", "/quit"):
            return True

        if cmd == "/help":
            Renderer.out(self._HELP)
            return False

        if cmd == "/reset":
            self.ctx.reset()
            Renderer.out("history cleared")
            return False

        if cmd == "/model":
            if not arg:
                Renderer.out(f"model = {self.ctx.model or 'auto'}")
                return False
            if arg == "clear":
                self.ctx.set_model(None)
                Renderer.out("model → auto(用 upstream.model 兜底)")
                return False
            self.ctx.set_model(arg)
            Renderer.out(f"model → {self.ctx.model}")
            return False

        if cmd == "/server_api":
            if not arg:
                Renderer.out(f"server_api = {self.ctx.server_api.value}")
                return False
            try:
                new_server_api = ServerApi(arg)
            except ValueError:
                Renderer.error_bubble(
                    f"server_api 必须是 messages/completions/responses,收到 {arg!r}"
                )
                return False
            self.ctx.set_server_api(new_server_api)
            Renderer.out(f"server_api → {new_server_api.value}")
            return False

        if cmd == "/raw":
            if not arg:
                Renderer.out(f"raw = {'on' if self.raw else 'off'}")
                return False
            if arg == "on":
                self.raw = True
                Renderer.out("raw → on")
                return False
            if arg == "off":
                self.raw = False
                Renderer.out("raw → off")
                return False
            Renderer.error_bubble("/raw 参数必须是 on 或 off")
            return False

        if cmd == "/raw_edge":
            if not arg:
                Renderer.out(f"raw_edge = {self.raw_edge}")
                return False
            value = _parse_positive_int(arg)
            if value is None:
                Renderer.error_bubble("/raw_edge 参数必须是正整数")
                return False
            self.raw_edge = value
            Renderer.out(f"raw_edge → {value}")
            return False

        if cmd == "/raw_step":
            if not arg:
                Renderer.out(f"raw_step = {self.raw_step}")
                return False
            value = _parse_positive_int(arg)
            if value is None:
                Renderer.error_bubble("/raw_step 参数必须是正整数")
                return False
            self.raw_step = value
            Renderer.out(f"raw_step → {value}")
            return False

        Renderer.error_bubble(f"未知命令 {cmd!r};/help 查看可用命令")
        return False


def _parse_positive_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _noop(_: str) -> None:
    pass
