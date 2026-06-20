"""Raw chat request/response helpers shared by CLI debug output."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RawChatRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass(frozen=True)
class RawSseFrame:
    received_at: str
    raw: str
    event: str | None
    data: dict[str, Any]


@dataclass(frozen=True)
class RawChatError:
    status: int
    body: str


@dataclass(frozen=True)
class RawChatResponse:
    frames: list[RawSseFrame]
    error: RawChatError | None = None


@dataclass
class RawChatTurn:
    request: RawChatRequest | None = None
    response: RawChatResponse | None = None


@dataclass(frozen=True)
class RawResponseFramePreview:
    text: str
    is_truncated: bool
    hidden_frames: int


def format_raw_request(request: RawChatRequest | None) -> str:
    if request is None:
        return "request pending"
    lines = [f"POST {request.url}"]
    lines.extend(f"{key}: {value}" for key, value in request.headers.items())
    lines.append("")
    lines.append(json.dumps(request.body, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def format_raw_response(response: RawChatResponse) -> str:
    parts = [_format_raw_sse_frame(frame) for frame in response.frames]
    if response.error is not None:
        parts.append(f"[error]\nHTTP {response.error.status}\n{response.error.body}")
    return "\n\n".join(part for part in parts if part)


def preview_raw_response_frames(
    response: RawChatResponse,
    *,
    edge_frames: int,
    revealed_middle_frames: int,
) -> RawResponseFramePreview:
    total = len(response.frames)
    edge = max(0, edge_frames)
    revealed = max(0, revealed_middle_frames)
    middle_start = edge
    middle_end = max(middle_start, total - edge)
    middle_total = max(0, middle_end - middle_start)
    revealed_middle = min(revealed, middle_total)
    hidden_frames = max(0, middle_total - revealed_middle)

    if hidden_frames == 0:
        return RawResponseFramePreview(
            text=format_raw_response(response),
            is_truncated=False,
            hidden_frames=0,
        )

    head_and_revealed = [
        *response.frames[:edge],
        *response.frames[middle_start : middle_start + revealed_middle],
    ]
    tail = response.frames[total - edge :]
    parts = [
        format_raw_response(RawChatResponse(frames=head_and_revealed)),
        f"... hidden {hidden_frames} frames ...",
        format_raw_response(RawChatResponse(frames=tail, error=response.error)),
    ]
    return RawResponseFramePreview(
        text="\n\n".join(part for part in parts if part),
        is_truncated=True,
        hidden_frames=hidden_frames,
    )


def format_raw_turn(
    turn: RawChatTurn,
    *,
    edge_frames: int,
    revealed_middle_frames: int,
    full: bool = False,
) -> str:
    response = turn.response or RawChatResponse(frames=[])
    response_text = (
        format_raw_response(response)
        if full
        else preview_raw_response_frames(
            response,
            edge_frames=edge_frames,
            revealed_middle_frames=revealed_middle_frames,
        ).text
    )
    return "\n\n".join(
        [
            "=== request ===",
            format_raw_request(turn.request),
            "=== response ===",
            response_text,
        ]
    )


def _format_raw_sse_frame(frame: RawSseFrame) -> str:
    event_label = f" event: {frame.event}" if frame.event else ""
    body_lines = [line for line in frame.raw.rstrip().splitlines() if not line.startswith("event:")]
    return "\n".join([f"[{frame.received_at}]{event_label}", *body_lines])
