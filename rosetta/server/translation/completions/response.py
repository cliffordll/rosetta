"""OpenAI Chat Completions 响应体 ↔ ResponseIR / StreamEvent。

非流:`completions_response_to_ir` / `ir_to_completions_response`。
流式:`completions_stream_to_ir` / `ir_to_completions_stream`。

流式状态机(OpenAI 粒度粗 → IR 粒度细的映射)
---------------------------------------------
OpenAI 流的 chunk 粒度较粗:
- 首个 chunk 通常 `delta={"role":"assistant"}`,没有内容
- 后续 chunk `delta={"content":"tok"}` 或 `delta={"tool_calls":[...]}`
- 结束 chunk `delta={}, finish_reason="stop"`
- 可选 usage chunk `choices=[], usage={...}`
- 最后 `data: [DONE]`(SSE 帧层,forwarder 处理,adapter 不见)

IR 粒度更细(Anthropic 风):显式的 `content_block_start` / `_delta` / `_stop`。
adapter 负责在首次看到 `delta.content` 或 `delta.tool_calls[i]` 时 **补开** 对应 block,
在 `finish_reason` 出现时关闭所有未关 block。

stop_reason / finish_reason 双向枚举映射见 `_FINISH_TO_STOP` / `_STOP_TO_FINISH`。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any, cast

from rosetta.server.translation.ir import (
    BlockStartEvent,
    BlockStopEvent,
    ContentBlock,
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    PingEvent,
    ResponseIR,
    SignatureDeltaEvent,
    StopReason,
    StreamEvent,
    TextBlock,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ToolUseBlock,
    Usage,
    UsageDelta,
)

# finish_reason → IR stop_reason(非对称:`function_call` 是 legacy,也映射到 tool_use)
_FINISH_TO_STOP: dict[str, StopReason] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "refusal",
    "function_call": "tool_use",
}

# IR stop_reason → finish_reason(反方向;无 OpenAI 对应的归到近似值)
_STOP_TO_FINISH: dict[StopReason, str] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "stop_sequence": "stop",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
    "refusal": "content_filter",
}


# ---------- Non-stream ----------


def completions_response_to_ir(body: dict[str, Any]) -> ResponseIR:
    """OpenAI /v1/chat/completions 非流响应 → ResponseIR。"""
    for required in ("id", "model", "choices"):
        if required not in body:
            raise ValueError(f"Chat Completions 响应缺少字段: {required}")

    choices_raw = body["choices"]
    if not isinstance(choices_raw, list):
        raise ValueError("choices 必须是 list")
    choices = cast(list[Any], choices_raw)
    if len(choices) != 1:
        raise ValueError(f"Chat Completions v0.1 只支持 n=1;收到 {len(choices)} 个 choices")

    raw_choice = choices[0]
    if not isinstance(raw_choice, dict):
        raise ValueError("choice 必须是 dict")
    choice = cast(dict[str, Any], raw_choice)
    raw_msg: Any = choice.get("message") or {}
    if not isinstance(raw_msg, dict):
        raise ValueError("choice.message 必须是 dict")
    msg = cast(dict[str, Any], raw_msg)

    content_blocks: list[ContentBlock] = []
    msg_content = msg.get("content")
    if isinstance(msg_content, str):
        if msg_content:
            content_blocks.append(TextBlock(text=msg_content))
    elif isinstance(msg_content, list):
        for part in cast(list[Any], msg_content):
            if not isinstance(part, dict):
                raise ValueError(f"message.content part 必须是 dict: {part!r}")
            p = cast(dict[str, Any], part)
            if p.get("type") != "text":
                raise ValueError(f"message.content 不支持的 part.type: {p.get('type')!r}")
            content_blocks.append(TextBlock(text=str(p.get("text", ""))))
    elif msg_content is not None:
        raise ValueError(
            f"message.content 必须是 str / list / None,收到 {type(msg_content).__name__}"
        )

    raw_tcs = msg.get("tool_calls")
    if raw_tcs:
        if not isinstance(raw_tcs, list):
            raise ValueError("message.tool_calls 必须是 list")
        for raw_tc in cast(list[Any], raw_tcs):
            if not isinstance(raw_tc, dict):
                raise ValueError(f"tool_call 必须是 dict: {raw_tc!r}")
            tc = cast(dict[str, Any], raw_tc)
            if tc.get("type", "function") != "function":
                raise ValueError(f"tool_call.type 必须是 function,收到 {tc.get('type')!r}")
            tc_id = tc.get("id")
            if not isinstance(tc_id, str):
                raise ValueError("tool_call.id 必须是 str")
            fn = tc.get("function")
            if not isinstance(fn, dict):
                raise ValueError("tool_call.function 必须是 dict")
            fn_d = cast(dict[str, Any], fn)
            name = fn_d.get("name")
            if not isinstance(name, str):
                raise ValueError("tool_call.function.name 必须是 str")
            args_str = fn_d.get("arguments", "")
            if not isinstance(args_str, str):
                raise ValueError("tool_call.function.arguments 必须是 str")
            parsed_input: dict[str, Any] = (
                cast(dict[str, Any], json.loads(args_str)) if args_str.strip() else {}
            )
            content_blocks.append(ToolUseBlock(id=tc_id, name=name, input=parsed_input))

    finish = choice.get("finish_reason")
    stop_reason: StopReason | None = None
    if finish is not None:
        if not isinstance(finish, str) or finish not in _FINISH_TO_STOP:
            raise ValueError(f"未知 finish_reason: {finish!r}")
        stop_reason = _FINISH_TO_STOP[finish]

    raw_usage: Any = body.get("usage") or {}
    if not isinstance(raw_usage, dict):
        raise ValueError("usage 必须是 dict")
    usage_d = cast(dict[str, Any], raw_usage)
    usage = Usage(
        input_tokens=int(usage_d.get("prompt_tokens", 0)),
        output_tokens=int(usage_d.get("completion_tokens", 0)),
    )

    return ResponseIR(
        id=str(body["id"]),
        model=str(body["model"]),
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    )


def ir_to_completions_response(ir: ResponseIR) -> dict[str, Any]:
    """ResponseIR → OpenAI /v1/chat/completions 非流响应。

    `object` 字段恒为 `"chat.completion"`;`created` 填占位 `0`(元信息,不保留)。
    """
    text_blocks: list[TextBlock] = []
    tool_uses: list[ToolUseBlock] = []
    for block in ir.content:
        if isinstance(block, TextBlock):
            text_blocks.append(block)
        elif isinstance(block, ToolUseBlock):
            tool_uses.append(block)
        else:
            raise ValueError(f"Chat Completions 响应不支持的 block 类型: {type(block).__name__}")

    msg: dict[str, Any] = {"role": "assistant"}
    if text_blocks:
        if len(text_blocks) == 1:
            msg["content"] = text_blocks[0].text
        else:
            msg["content"] = [{"type": "text", "text": b.text} for b in text_blocks]
    else:
        msg["content"] = None

    if tool_uses:
        msg["tool_calls"] = [
            {
                "id": b.id,
                "type": "function",
                "function": {
                    "name": b.name,
                    "arguments": json.dumps(b.input, ensure_ascii=False),
                },
            }
            for b in tool_uses
        ]

    finish_reason: str | None = (
        _STOP_TO_FINISH[ir.stop_reason] if ir.stop_reason is not None else None
    )

    return {
        "id": ir.id,
        "object": "chat.completion",
        "created": 0,
        "model": ir.model,
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": ir.usage.input_tokens,
            "completion_tokens": ir.usage.output_tokens,
            "total_tokens": ir.usage.input_tokens + ir.usage.output_tokens,
        },
    }


# ---------- Stream (OpenAI → IR) ----------


def completions_stream_to_ir(
    chunks: Iterable[dict[str, Any]],
) -> Iterator[StreamEvent]:
    """OpenAI chat.completion.chunk JSON 流 → IR StreamEvent 流。

    状态:
    - `started`:是否已发 `MessageStart`
    - `text_ir_idx`:若 text block 已开,记其 IR 索引;未开为 None
    - `tool_idx_map`:OpenAI `tool_calls[].index` → IR block 索引
    - `next_ir_idx`:下一个 IR block 索引
    - `finalized`:是否见过 `finish_reason`(用于决定是否 emit MessageStop)
    """
    started = False
    text_ir_idx: int | None = None
    tool_idx_map: dict[int, int] = {}
    next_ir_idx = 0
    finalized = False
    last_id = ""
    last_model = ""

    for chunk in chunks:
        if not started:
            last_id = str(chunk.get("id", ""))
            last_model = str(chunk.get("model", ""))
            yield MessageStartEvent(id=last_id, model=last_model, usage=Usage())
            started = True

        choices_raw = chunk.get("choices")
        choices: list[Any] = cast(list[Any], choices_raw) if isinstance(choices_raw, list) else []

        if choices:
            if len(choices) != 1:
                raise ValueError(f"stream 不支持 n>1;收到 {len(choices)} 个 choices")
            raw_choice = choices[0]
            if not isinstance(raw_choice, dict):
                raise ValueError("choice 必须是 dict")
            choice = cast(dict[str, Any], raw_choice)
            raw_delta: Any = choice.get("delta") or {}
            if not isinstance(raw_delta, dict):
                raise ValueError("choice.delta 必须是 dict")
            delta = cast(dict[str, Any], raw_delta)

            # delta.content —— 首次出现就补开 text block
            content_val = delta.get("content")
            if isinstance(content_val, str) and content_val:
                if text_ir_idx is None:
                    text_ir_idx = next_ir_idx
                    next_ir_idx += 1
                    yield BlockStartEvent(index=text_ir_idx, block=TextBlock(text=""))
                yield TextDeltaEvent(index=text_ir_idx, text=content_val)

            # delta.tool_calls —— 首次看到某个 OpenAI index 就补开 ToolUseBlock
            raw_tcs = delta.get("tool_calls")
            if raw_tcs:
                if not isinstance(raw_tcs, list):
                    raise ValueError("delta.tool_calls 必须是 list")
                for raw_tc in cast(list[Any], raw_tcs):
                    if not isinstance(raw_tc, dict):
                        raise ValueError(f"tool_call delta 必须是 dict: {raw_tc!r}")
                    tc = cast(dict[str, Any], raw_tc)
                    oai_idx_val = tc.get("index", 0)
                    if not isinstance(oai_idx_val, int):
                        raise ValueError(f"tool_call.index 必须是 int: {oai_idx_val!r}")
                    fn_val: Any = tc.get("function") or {}
                    if not isinstance(fn_val, dict):
                        raise ValueError("tool_call.function 必须是 dict")
                    fn = cast(dict[str, Any], fn_val)

                    if oai_idx_val not in tool_idx_map:
                        # 切换到 tool block → 若 text block 还开着,先关
                        if text_ir_idx is not None:
                            yield BlockStopEvent(index=text_ir_idx)
                            text_ir_idx = None
                        ir_idx = next_ir_idx
                        next_ir_idx += 1
                        tool_idx_map[oai_idx_val] = ir_idx
                        tc_id_val = tc.get("id")
                        tc_name_val = fn.get("name")
                        if not isinstance(tc_id_val, str):
                            raise ValueError("首个 tool_call delta 必须带 id (str)")
                        if not isinstance(tc_name_val, str):
                            raise ValueError("首个 tool_call delta 必须带 function.name (str)")
                        yield BlockStartEvent(
                            index=ir_idx,
                            block=ToolUseBlock(id=tc_id_val, name=tc_name_val, input={}),
                        )
                        args = fn.get("arguments")
                        if isinstance(args, str) and args:
                            yield InputJsonDeltaEvent(index=ir_idx, partial_json=args)
                    else:
                        ir_idx = tool_idx_map[oai_idx_val]
                        args = fn.get("arguments")
                        if isinstance(args, str) and args:
                            yield InputJsonDeltaEvent(index=ir_idx, partial_json=args)

            # finish_reason —— 关闭所有未关 block,emit MessageDelta
            finish_val = choice.get("finish_reason")
            if finish_val is not None:
                if text_ir_idx is not None:
                    yield BlockStopEvent(index=text_ir_idx)
                    text_ir_idx = None
                for ir_idx in tool_idx_map.values():
                    yield BlockStopEvent(index=ir_idx)
                tool_idx_map.clear()
                if not isinstance(finish_val, str) or finish_val not in _FINISH_TO_STOP:
                    raise ValueError(f"未知 finish_reason: {finish_val!r}")
                yield MessageDeltaEvent(stop_reason=_FINISH_TO_STOP[finish_val])
                finalized = True

        # usage chunk(可能与 finish_reason 同 chunk,也可能单独)
        raw_usage = chunk.get("usage")
        if raw_usage is not None:
            if not isinstance(raw_usage, dict):
                raise ValueError("chunk.usage 必须是 dict")
            u = cast(dict[str, Any], raw_usage)
            yield MessageDeltaEvent(
                usage=UsageDelta(
                    input_tokens=u.get("prompt_tokens"),
                    output_tokens=u.get("completion_tokens"),
                )
            )

    if finalized:
        yield MessageStopEvent()


# ---------- Stream (IR → OpenAI) ----------


def ir_to_completions_stream(
    events: Iterable[StreamEvent],
) -> Iterator[dict[str, Any]]:
    """IR StreamEvent 流 → OpenAI chat.completion.chunk 流。

    OpenAI 没有显式的 `content_block_start` / `_stop`,所以 `BlockStart(TextBlock)`
    和所有 `BlockStop` 不产生 chunk;`BlockStart(ToolUseBlock)` 产生带 id/name 的
    首 chunk;`TextDelta` / `InputJsonDelta` 各自产生 delta chunk;
    `MessageDelta(stop_reason)` 产生带 `finish_reason` 的 chunk;
    `MessageDelta(usage)` 产生独立的 usage chunk(`choices=[]`);
    `MessageStop` / `Ping` 丢弃(OpenAI 流结束靠 SSE 层 `[DONE]`,forwarder 处理)。
    """
    last_id = ""
    last_model = ""
    ir_to_oai_tool: dict[int, int] = {}
    next_oai_tool_idx = 0

    for ev in events:
        if isinstance(ev, MessageStartEvent):
            last_id = ev.id
            last_model = ev.model
            yield _make_chunk(last_id, last_model, {"role": "assistant"})
        elif isinstance(ev, BlockStartEvent):
            block = ev.block
            if isinstance(block, TextBlock):
                # 无 chunk;text block 的首个 delta 才产生带 content 的 chunk
                continue
            if isinstance(block, ToolUseBlock):
                oai_idx = next_oai_tool_idx
                next_oai_tool_idx += 1
                ir_to_oai_tool[ev.index] = oai_idx
                yield _make_chunk(
                    last_id,
                    last_model,
                    {
                        "tool_calls": [
                            {
                                "index": oai_idx,
                                "id": block.id,
                                "type": "function",
                                "function": {"name": block.name, "arguments": ""},
                            }
                        ]
                    },
                )
            else:
                raise ValueError(f"Chat Completions 流式不支持 block: {type(block).__name__}")
        elif isinstance(ev, TextDeltaEvent):
            yield _make_chunk(last_id, last_model, {"content": ev.text})
        elif isinstance(ev, InputJsonDeltaEvent):
            oai_idx = ir_to_oai_tool.get(ev.index, -1)
            if oai_idx < 0:
                raise ValueError(f"InputJsonDelta 对应的 IR block {ev.index} 未开启 ToolUse")
            yield _make_chunk(
                last_id,
                last_model,
                {
                    "tool_calls": [
                        {
                            "index": oai_idx,
                            "function": {"arguments": ev.partial_json},
                        }
                    ]
                },
            )
        elif isinstance(ev, BlockStopEvent):
            # OpenAI 无对应事件;丢弃
            continue
        elif isinstance(ev, MessageDeltaEvent):
            if ev.stop_reason is not None:
                yield _make_chunk(
                    last_id,
                    last_model,
                    {},
                    finish_reason=_STOP_TO_FINISH[ev.stop_reason],
                )
            if ev.usage is not None:
                pt = ev.usage.input_tokens or 0
                ct = ev.usage.output_tokens or 0
                yield {
                    "id": last_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": last_model,
                    "choices": [],
                    "usage": {
                        "prompt_tokens": pt,
                        "completion_tokens": ct,
                        "total_tokens": pt + ct,
                    },
                }
        elif isinstance(ev, (MessageStopEvent, PingEvent)):
            # OpenAI 流结束不发事件(SSE 层 [DONE] 在 forwarder);Ping 在 OpenAI 无对应
            continue
        elif isinstance(ev, (ThinkingDeltaEvent, SignatureDeltaEvent)):
            raise ValueError(f"Chat Completions 流式不支持事件: {type(ev).__name__}")
        else:
            # union 穷尽:narrow 到 ErrorEvent。v0.1 抛到调用方,由 stream 编排层
            # 决定如何终止(见 DESIGN §8.3)
            raise ValueError(f"stream ErrorEvent: {ev.error_type}: {ev.message}")


def _make_chunk(
    id_: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id_,
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
