from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from rosetta.shared.server_api import ServerApi

LogContentMode = Literal["none", "summary", "full"]
LogsPageSize = Literal[10, 20, 50, 100]

LOG_CONTENT_KEY = "logs:log_content"
LOGS_PAGE_SIZE_KEY = "logs:page_size"
LOG_CONTENT_DEFAULT: LogContentMode = "summary"
LOGS_PAGE_SIZE_DEFAULT: LogsPageSize = 20
LOGS_PAGE_SIZE_OPTIONS: tuple[LogsPageSize, ...] = (10, 20, 50, 100)
SUMMARY_TEXT_LIMIT = 240


@dataclass(frozen=True)
class LogsConfig:
    log_content: LogContentMode = LOG_CONTENT_DEFAULT
    page_size: LogsPageSize = LOGS_PAGE_SIZE_DEFAULT


def normalize_log_content(value: str | None) -> LogContentMode:
    if value in ("none", "summary", "full"):
        return value
    return LOG_CONTENT_DEFAULT


def normalize_logs_page_size(value: int | str | None) -> LogsPageSize:
    try:
        parsed = int(value) if value is not None else LOGS_PAGE_SIZE_DEFAULT
    except (TypeError, ValueError):
        return LOGS_PAGE_SIZE_DEFAULT
    if parsed == 10:
        return 10
    if parsed == 20:
        return 20
    if parsed == 50:
        return 50
    if parsed == 100:
        return 100
    return LOGS_PAGE_SIZE_DEFAULT


def summarize_text(text: str | None, *, limit: int = SUMMARY_TEXT_LIMIT) -> str | None:
    if text is None:
        return None
    compact = " ".join(text.split())
    if not compact:
        return None
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def apply_log_content_mode(mode: LogContentMode, text: str | None) -> str | None:
    if mode == "none":
        return None
    if mode == "summary":
        return summarize_text(text)
    if text is None:
        return None
    return text.strip() or None


def request_text_for(server_api: ServerApi, body: dict[str, Any]) -> str | None:
    if server_api in (ServerApi.MESSAGES, ServerApi.CHAT_COMPLETIONS):
        messages = body.get("messages")
        if not isinstance(messages, list):
            return None
        parts: list[str] = []
        for msg in cast(list[Any], messages):
            if not isinstance(msg, dict):
                continue
            md = cast(dict[str, Any], msg)
            if md.get("role") != "user":
                continue
            text = _content_text(md.get("content"))
            if text:
                parts.append(text)
        return "\n".join(parts) or None

    return _content_text(body.get("input"))


def response_text_for(server_api: ServerApi, data: dict[str, Any]) -> str | None:
    text = ""
    if server_api is ServerApi.MESSAGES:
        blocks = data.get("content", [])
        if isinstance(blocks, list):
            parts: list[str] = []
            for block in cast(list[Any], blocks):
                if isinstance(block, dict):
                    bd = cast(dict[str, Any], block)
                    if bd.get("type") == "text":
                        value = bd.get("text")
                        if isinstance(value, str):
                            parts.append(value)
            text = "".join(parts)
    elif server_api is ServerApi.CHAT_COMPLETIONS:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = cast(Any, choices[0])
            if isinstance(first, dict):
                message = cast(dict[str, Any], first).get("message")
                if isinstance(message, dict):
                    content = cast(dict[str, Any], message).get("content")
                    if isinstance(content, str):
                        text = content
    else:
        output = data.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in cast(list[Any], output):
                if not isinstance(item, dict):
                    continue
                it = cast(dict[str, Any], item)
                if it.get("type") != "message":
                    continue
                content = it.get("content")
                if not isinstance(content, list):
                    continue
                for chunk in cast(list[Any], content):
                    if not isinstance(chunk, dict):
                        continue
                    cd = cast(dict[str, Any], chunk)
                    if cd.get("type") == "output_text":
                        value = cd.get("text")
                        if isinstance(value, str):
                            parts.append(value)
            text = "".join(parts)
    return _strip_mock_echo(text)


class SseTextCollector:
    def __init__(self, server_api: ServerApi) -> None:
        self.server_api = server_api
        self._buffer = b""
        self._parts: list[str] = []

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while True:
            sep_idx = -1
            sep_len = 0
            for sep in (b"\r\n\r\n", b"\n\n"):
                idx = self._buffer.find(sep)
                if idx != -1 and (sep_idx == -1 or idx < sep_idx):
                    sep_idx = idx
                    sep_len = len(sep)
            if sep_idx == -1:
                break
            frame = self._buffer[:sep_idx]
            self._buffer = self._buffer[sep_idx + sep_len :]
            self._consume_frame(frame)

    def finish(self) -> None:
        if self._buffer.strip():
            self._consume_frame(self._buffer)
        self._buffer = b""

    @property
    def text(self) -> str | None:
        return _strip_mock_echo("".join(self._parts))

    def _consume_frame(self, frame: bytes) -> None:
        parsed = _parse_sse_frame(frame)
        if parsed is None:
            return
        event_name, data = parsed
        text = _extract_sse_text(self.server_api, event_name, data)
        if text:
            self._parts.append(text)


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        items = cast(list[Any], value)
        parts = [_content_text(item) for item in items]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        data = cast(dict[str, Any], value)
        if isinstance(data.get("text"), str):
            return cast(str, data["text"]).strip()
        if isinstance(data.get("input_text"), str):
            return cast(str, data["input_text"]).strip()
        if isinstance(data.get("output_text"), str):
            return cast(str, data["output_text"]).strip()
        if "content" in data:
            return _content_text(data.get("content"))
    return ""


def _strip_mock_echo(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("[mock:"):
        marker = "] echo:"
        idx = stripped.find(marker)
        if idx != -1:
            candidate = stripped[idx + len(marker) :].strip()
            return candidate or None
    return stripped


def _parse_sse_frame(frame: bytes) -> tuple[str | None, dict[str, Any]] | None:
    event_name: str | None = None
    data_lines: list[str] = []
    for raw_line in frame.split(b"\n"):
        line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    if not data_lines:
        return None
    payload = "\n".join(data_lines)
    if payload.strip() == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return event_name, cast(dict[str, Any], data)


def _extract_sse_text(server_api: ServerApi, event_name: str | None, data: dict[str, Any]) -> str:
    if server_api is ServerApi.MESSAGES:
        etype = event_name or data.get("type")
        if etype != "content_block_delta":
            return ""
        delta = data.get("delta")
        if not isinstance(delta, dict):
            return ""
        dd = cast(dict[str, Any], delta)
        if dd.get("type") != "text_delta":
            return ""
        text = dd.get("text")
        return text if isinstance(text, str) else ""

    if server_api is ServerApi.CHAT_COMPLETIONS:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = cast(Any, choices[0])
        if not isinstance(first, dict):
            return ""
        delta = cast(dict[str, Any], first).get("delta")
        if not isinstance(delta, dict):
            return ""
        content = cast(dict[str, Any], delta).get("content")
        return content if isinstance(content, str) else ""

    etype = event_name or data.get("type")
    if etype != "response.output_text.delta":
        return ""
    delta = data.get("delta")
    return delta if isinstance(delta, str) else ""


# ── Chat config ──────────────────────────────────────────────────────────

CHAT_MAX_TOKENS_KEY = "chat:max_tokens"
CHAT_STREAM_KEY = "chat:stream"
CHAT_MAX_TOKENS_DEFAULT = 8192
CHAT_STREAM_DEFAULT = True


def normalize_chat_max_tokens(value: str | None) -> int:
    if value is None:
        return CHAT_MAX_TOKENS_DEFAULT
    try:
        v = int(value)
        return v if v > 0 else CHAT_MAX_TOKENS_DEFAULT
    except (TypeError, ValueError):
        return CHAT_MAX_TOKENS_DEFAULT


def normalize_chat_stream(value: str | None) -> bool:
    if value is None:
        return CHAT_STREAM_DEFAULT
    return value.strip().lower() == "true"


@dataclass(frozen=True)
class ChatConfig:
    max_tokens: int = CHAT_MAX_TOKENS_DEFAULT
    stream: bool = CHAT_STREAM_DEFAULT
