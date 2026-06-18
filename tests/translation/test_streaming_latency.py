"""跨格式 SSE 翻译的增量输出测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from rosetta.server.translation.dispatcher import translate_stream_bytes
from rosetta.shared.protocols import Protocol


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
        source=Protocol.MESSAGES,
        target=Protocol.MESSAGES,
    )

    first = await asyncio.wait_for(translated.__anext__(), timeout=0.2)
    assert b"message_start" in first

    release_second_chunk.set()
    second = await asyncio.wait_for(translated.__anext__(), timeout=0.2)
    assert b"message_stop" in second
