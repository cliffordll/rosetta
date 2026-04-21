"""本地 mock 上游:假装是 Anthropic / OpenAI,用于 1.3 直通验证。

跑起来:
    uv run python -m tests.mock_upstream [--port 8765]

端点:
    POST /v1/messages         假装 Anthropic Messages(非流式 + SSE 流式)
    POST /v1/chat/completions 假装 OpenAI Chat Completions(非流式 + SSE 流式)

关键:
    - 不校验 api_key(随便填),只按请求体 `stream: true` 切分非流式/流式
    - 返回体结构贴近真上游,允许官方 SDK 解析(但不保证所有字段完备)
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="mock-upstream", description="rosetta 1.3 直通验证用假上游")


@app.post("/v1/messages", response_model=None)
async def mock_messages(request: Request) -> JSONResponse | StreamingResponse:
    body = cast(dict[str, Any], await request.json())
    if bool(body.get("stream", False)):
        return StreamingResponse(_mock_messages_stream(body), media_type="text/event-stream")
    return JSONResponse(_mock_messages_response(body))


@app.post("/v1/chat/completions", response_model=None)
async def mock_chat(request: Request) -> JSONResponse | StreamingResponse:
    body = cast(dict[str, Any], await request.json())
    if bool(body.get("stream", False)):
        return StreamingResponse(_mock_chat_stream(body), media_type="text/event-stream")
    return JSONResponse(_mock_chat_response(body))


def _mock_messages_response(req: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "msg_mock_001",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "mock messages ack"}],
        "model": req.get("model", "claude-unknown"),
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 5, "output_tokens": 5},
    }


async def _mock_messages_stream(req: dict[str, Any]) -> AsyncIterator[bytes]:
    model = req.get("model", "claude-unknown")
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_mock_002",
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "usage": {"input_tokens": 5, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "mock "},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "stream "},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "ack"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 3},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    for name, payload in events:
        yield f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


def _mock_chat_response(req: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "chatcmpl_mock_001",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.get("model", "gpt-unknown"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "mock chat ack"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


async def _mock_chat_stream(req: dict[str, Any]) -> AsyncIterator[bytes]:
    model = req.get("model", "gpt-unknown")
    deltas = ["mock ", "stream ", "ack"]
    for i, d in enumerate(deltas):
        delta_obj: dict[str, Any] = (
            {"role": "assistant", "content": d} if i == 0 else {"content": d}
        )
        chunk = {
            "id": "chatcmpl_mock_002",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": delta_obj, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n".encode()
    # 结束 chunk 带 finish_reason + OpenAI 的 [DONE] sentinel
    final = {
        "id": "chatcmpl_mock_002",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="rosetta 1.3 mock upstream")
    parser.add_argument("--port", type=int, default=8765, help="监听端口,默认 8765")
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
