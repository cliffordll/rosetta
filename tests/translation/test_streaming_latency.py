"""跨格式 SSE 翻译的增量输出测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from rosetta.server.translation.dispatcher import translate_stream_bytes
from rosetta.shared.server_api import ServerApi


async def test_translate_stream_bytes_yields_first_frame_before_upstream_finishes() -> None:
    """收到完整首帧后应立即产出,不能等待上游流结束。"""
    release_second_chunk = asyncio.Event()

    async def raw_chunks() -> AsyncIterator[bytes]:
        yield (
            b"event: message_start\n"
            b'data: {"type":"message_start","message":{"id":"msg_1","type":"message",'
            b'"role":"assistant","content":[],"model":"claude-haiku-4-5",'
            b'"stop_reason":null,"stop_sequence":null,'
            b'"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
        )
        await release_second_chunk.wait()
        yield (b'event: message_stop\ndata: {"type":"message_stop"}\n\n')

    translated = translate_stream_bytes(
        raw_chunks(),
        source=ServerApi.MESSAGES,
        target=ServerApi.MESSAGES,
    )

    first = await asyncio.wait_for(translated.__anext__(), timeout=0.2)
    assert b"message_start" in first

    release_second_chunk.set()
    second = await asyncio.wait_for(translated.__anext__(), timeout=0.2)
    assert b"message_stop" in second


async def test_completions_stream_without_finish_reason_still_completes_responses() -> None:
    """Some OpenAI-compatible upstreams end with [DONE] but omit finish_reason."""

    async def raw_chunks() -> AsyncIterator[bytes]:
        yield (
            b'data: {"id":"chatcmpl_1","object":"chat.completion.chunk",'
            b'"created":0,"model":"demo","choices":[{"index":0,'
            b'"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        )
        yield (
            b'data: {"id":"chatcmpl_1","object":"chat.completion.chunk",'
            b'"created":0,"model":"demo","choices":[{"index":0,'
            b'"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
        )
        yield b"data: [DONE]\n\n"

    translated = [
        chunk
        async for chunk in translate_stream_bytes(
            raw_chunks(),
            source=ServerApi.CHAT_COMPLETIONS,
            target=ServerApi.RESPONSES,
        )
    ]

    assert any(b"response.completed" in chunk for chunk in translated)


async def test_completions_tool_delta_without_initial_name_still_completes() -> None:
    """Some compatible upstreams stream tool args before id/name metadata."""

    def frame(payload: dict[str, object]) -> bytes:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()

    async def raw_chunks() -> AsyncIterator[bytes]:
        yield frame(
            {
                "id": "chatcmpl_1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "demo",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '{"city'}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
        )
        yield frame(
            {
                "id": "chatcmpl_1",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "demo",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_weather",
                                        "arguments": '":"上海"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )
        yield b"data: [DONE]\n\n"

    translated = [
        chunk
        async for chunk in translate_stream_bytes(
            raw_chunks(),
            source=ServerApi.CHAT_COMPLETIONS,
            target=ServerApi.RESPONSES,
        )
    ]

    text = b"".join(translated)
    assert b"response.completed" in text
    assert b"get_weather" in text


async def test_completions_length_finish_emits_response_completed_event() -> None:
    """Responses stream clients wait for response.completed even when status is incomplete."""

    async def raw_chunks() -> AsyncIterator[bytes]:
        yield (
            b'data: {"id":"chatcmpl_1","object":"chat.completion.chunk",'
            b'"created":0,"model":"demo","choices":[{"index":0,'
            b'"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
        )
        yield (
            b'data: {"id":"chatcmpl_1","object":"chat.completion.chunk",'
            b'"created":0,"model":"demo","choices":[{"index":0,'
            b'"delta":{},"finish_reason":"length"}]}\n\n'
        )
        yield b"data: [DONE]\n\n"

    translated = [
        chunk
        async for chunk in translate_stream_bytes(
            raw_chunks(),
            source=ServerApi.CHAT_COMPLETIONS,
            target=ServerApi.RESPONSES,
        )
    ]

    text = b"".join(translated)
    assert b"response.completed" in text
    assert b"response.incomplete" not in text
    assert b'"status": "incomplete"' in text
