"""REPL input helpers with optional prompt_toolkit completion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast


@dataclass(frozen=True)
class CompletionItem:
    text: str
    help: str


class ReplInput(Protocol):
    async def read(self, prompt: str) -> str: ...


SLASH_COMPLETIONS: tuple[CompletionItem, ...] = (
    CompletionItem("/exit", "退出 REPL"),
    CompletionItem("/quit", "退出 REPL"),
    CompletionItem("/reset", "清空对话历史"),
    CompletionItem("/model", "显示或切换模型"),
    CompletionItem("/server_api", "显示或切换 API 格式"),
    CompletionItem("/raw", "显示或切换 raw 输出"),
    CompletionItem("/raw_edge", "显示或设置 raw 前/后 frame 数"),
    CompletionItem("/raw_step", "保留配置;CLI 当前不交互展开"),
    CompletionItem("/api_key", "显示或切换 api_key"),
    CompletionItem("/upstream", "显示或切换 upstream"),
    CompletionItem("/max_tokens", "显示或切换 max_tokens"),
    CompletionItem("/stream", "显示或切换 stream 模式"),
    CompletionItem("/help", "显示帮助"),
)

SERVER_API_COMPLETIONS: tuple[CompletionItem, ...] = (
    CompletionItem("messages", "/v1/messages"),
    CompletionItem("completions", "/v1/chat/completions"),
    CompletionItem("responses", "/v1/responses"),
)

RAW_MODE_COMPLETIONS: tuple[CompletionItem, ...] = (
    CompletionItem("on", "开启 raw 输出"),
    CompletionItem("off", "关闭 raw 输出"),
)

MODEL_COMPLETIONS: tuple[CompletionItem, ...] = (
    CompletionItem("clear", "切回 auto(走 upstream.model 兜底)"),
)

CLEAR_COMPLETIONS: tuple[CompletionItem, ...] = (CompletionItem("clear", "清除覆盖,走默认值"),)


def complete_repl_input(text: str) -> list[CompletionItem]:
    """Return REPL completions for slash commands and supported command values."""
    if not text.startswith("/"):
        return []

    if " " in text:
        command, _, arg_prefix = text.partition(" ")
    else:
        command = text
        arg_prefix = None

    if arg_prefix is None:
        return [item for item in SLASH_COMPLETIONS if item.text.startswith(command)]

    if command == "/server_api":
        return [item for item in SERVER_API_COMPLETIONS if item.text.startswith(arg_prefix)]

    if command == "/raw":
        return [item for item in RAW_MODE_COMPLETIONS if item.text.startswith(arg_prefix)]

    if command == "/model":
        return [item for item in MODEL_COMPLETIONS if item.text.startswith(arg_prefix)]

    if command == "/stream":
        return [item for item in RAW_MODE_COMPLETIONS if item.text.startswith(arg_prefix)]

    if command in ("/api_key", "/upstream"):
        return [item for item in CLEAR_COMPLETIONS if item.text.startswith(arg_prefix)]

    return []


class StdInput:
    async def read(self, prompt: str) -> str:
        return input(prompt)


def make_repl_input() -> ReplInput:
    """Create a prompt_toolkit-backed input reader, falling back to plain input()."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.document import Document
    except ImportError:
        return StdInput()

    class ReplCompleter(Completer):
        def get_completions(self, document: Document, complete_event):  # type: ignore[no-untyped-def]
            word = document.get_word_before_cursor(WORD=True)
            for item in complete_repl_input(document.text_before_cursor):
                yield Completion(
                    item.text,
                    start_position=-len(word),
                    display=item.text,
                    display_meta=item.help,
                )

    try:
        prompt_session_factory = cast(Any, PromptSession)
        session = prompt_session_factory(completer=ReplCompleter(), complete_while_typing=True)
    except Exception:
        return StdInput()

    class PromptToolkitInput:
        async def read(self, prompt: str) -> str:
            return cast(str, await session.prompt_async(prompt))

    return PromptToolkitInput()
