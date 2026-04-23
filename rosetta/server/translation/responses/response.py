"""OpenAI Responses API 响应体 ↔ ResponseIR / StreamEvent。

非流响应(`/v1/responses` 返回 `{object:"response", output:[...], usage}`)
---------------------------------------------------------------------------

`output` 是 item 数组,可能含:
- `{"type":"message", "role":"assistant", "content":[{"type":"output_text","text":...}, ...]}`
- `{"type":"function_call", "call_id":..., "name":..., "arguments":"..."}`
- `{"type":"reasoning", ...}`(v0.1 原样识别但拒绝翻译到 IR,Responses→IR 时 raise)

`status`:`completed` / `incomplete` / `failed`。结合 `incomplete_details.reason` 映射到
IR `stop_reason`:
- `completed` + 无 function_call → `end_turn`
- `completed` + 有 function_call → `tool_use`
- `incomplete` + `reason=max_output_tokens` → `max_tokens`
- `incomplete` + `reason=content_filter` → `refusal`

流式响应
--------

Responses 流事件种类多,v0.1 覆盖以下(其余 raise):
- `response.created` → `MessageStart`(id/model)
- `response.output_item.added` type=message → 预期后续的 `content_part.added`
  → `BlockStart(TextBlock)`
- `response.output_item.added` type=function_call → `BlockStart(ToolUseBlock)`
- `response.output_text.delta` → `TextDelta`
- `response.function_call_arguments.delta` → `InputJsonDelta`
- `response.output_item.done` → `BlockStop`(对应 item)
- `response.completed` → `MessageDelta(stop_reason)` + `MessageStop`

反向:IR → Responses 事件按映射生成。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any, cast

from rosetta.server.translation.ir import (
    BlockStartEvent,
    BlockStopEvent,
    ContentBlock,
    ErrorEvent,
    InputJsonDeltaEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    PingEvent,
    ResponseIR,
    StopReason,
    StreamEvent,
    TextBlock,
    TextDeltaEvent,
    ToolUseBlock,
    Usage,
    UsageDelta,
)

# ---------- Non-stream ----------


def responses_response_to_ir(body: dict[str, Any]) -> ResponseIR:
    """OpenAI /v1/responses 非流响应 → ResponseIR。"""
    for required in ("id", "model", "output"):
        if required not in body:
            raise ValueError(f"Responses 响应缺少字段: {required}")

    raw_output = body["output"]
    if not isinstance(raw_output, list):
        raise ValueError("output 必须是 list")

    content_blocks: list[ContentBlock] = []
    has_tool_use = False
    for raw_item in cast(list[Any], raw_output):
        if not isinstance(raw_item, dict):
            raise ValueError(f"output item 必须是 dict: {raw_item!r}")
        item = cast(dict[str, Any], raw_item)
        itype = item.get("type")

        if itype == "message":
            if item.get("role") != "assistant":
                raise ValueError(
                    f"output message 的 role 只能是 assistant,收到 {item.get('role')!r}"
                )
            raw_content: Any = item.get("content") or []
            if not isinstance(raw_content, list):
                raise ValueError("output message.content 必须是 list")
            for raw_part in cast(list[Any], raw_content):
                if not isinstance(raw_part, dict):
                    raise ValueError(f"output message.content part 必须是 dict: {raw_part!r}")
                p = cast(dict[str, Any], raw_part)
                ptype = p.get("type")
                if ptype == "output_text":
                    content_blocks.append(TextBlock(text=str(p.get("text", ""))))
                else:
                    raise ValueError(f"output message.content 不支持的 part.type: {ptype!r}")
        elif itype == "function_call":
            has_tool_use = True
            call_id = item.get("call_id")
            name = item.get("name")
            args_str = item.get("arguments", "")
            if not isinstance(call_id, str):
                raise ValueError("function_call.call_id 必须是 str")
            if not isinstance(name, str):
                raise ValueError("function_call.name 必须是 str")
            if not isinstance(args_str, str):
                raise ValueError("function_call.arguments 必须是 str")
            parsed: dict[str, Any] = (
                cast(dict[str, Any], json.loads(args_str)) if args_str.strip() else {}
            )
            content_blocks.append(ToolUseBlock(id=call_id, name=name, input=parsed))
        elif itype == "reasoning":
            raise ValueError(
                "v0.1 不支持 output item.type=reasoning(IR thinking block "
                "需要 Responses 侧的扩展映射,预留到 v1+)"
            )
        else:
            raise ValueError(f"不支持的 output item.type: {itype!r}")

    stop_reason = _derive_stop_reason(body, has_tool_use=has_tool_use)
    usage = _parse_usage(body.get("usage"))

    return ResponseIR(
        id=str(body["id"]),
        model=str(body["model"]),
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    )


def _derive_stop_reason(body: dict[str, Any], has_tool_use: bool) -> StopReason | None:
    """从 Responses 的 `status` + `incomplete_details.reason` 推断 IR stop_reason。"""
    status = body.get("status")
    if status is None:
        return None
    if status == "completed":
        return "tool_use" if has_tool_use else "end_turn"
    if status == "incomplete":
        details: Any = body.get("incomplete_details") or {}
        if not isinstance(details, dict):
            raise ValueError("incomplete_details 必须是 dict")
        d = cast(dict[str, Any], details)
        reason = d.get("reason")
        if reason == "max_output_tokens":
            return "max_tokens"
        if reason == "content_filter":
            return "refusal"
        raise ValueError(f"未知 incomplete_details.reason: {reason!r}")
    if status == "failed":
        return "refusal"
    raise ValueError(f"未知 Responses status: {status!r}")


def _parse_usage(raw: Any) -> Usage:
    if raw is None:
        return Usage()
    if not isinstance(raw, dict):
        raise ValueError("usage 必须是 dict")
    u = cast(dict[str, Any], raw)
    return Usage(
        input_tokens=int(u.get("input_tokens", 0)),
        output_tokens=int(u.get("output_tokens", 0)),
    )


def ir_to_responses_response(ir: ResponseIR) -> dict[str, Any]:
    """ResponseIR → OpenAI /v1/responses 非流响应。"""
    text_blocks: list[TextBlock] = []
    tool_uses: list[ToolUseBlock] = []
    for block in ir.content:
        if isinstance(block, TextBlock):
            text_blocks.append(block)
        elif isinstance(block, ToolUseBlock):
            tool_uses.append(block)
        else:
            raise ValueError(f"Responses 响应不支持的 block 类型: {type(block).__name__}")

    output: list[dict[str, Any]] = []
    if text_blocks:
        output.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": b.text} for b in text_blocks],
            }
        )
    for tu in tool_uses:
        output.append(
            {
                "type": "function_call",
                "call_id": tu.id,
                "name": tu.name,
                "arguments": json.dumps(tu.input, ensure_ascii=False),
            }
        )

    status, incomplete_details = _stop_reason_to_status(ir.stop_reason)

    body: dict[str, Any] = {
        "id": ir.id,
        "object": "response",
        "created_at": 0,
        "model": ir.model,
        "output": output,
        "status": status,
        "usage": {
            "input_tokens": ir.usage.input_tokens,
            "output_tokens": ir.usage.output_tokens,
            "total_tokens": ir.usage.input_tokens + ir.usage.output_tokens,
        },
    }
    if incomplete_details is not None:
        body["incomplete_details"] = incomplete_details
    return body


def _stop_reason_to_status(
    stop_reason: StopReason | None,
) -> tuple[str, dict[str, str] | None]:
    """IR stop_reason → Responses (status, incomplete_details)。"""
    if stop_reason is None:
        return "completed", None
    if stop_reason in ("end_turn", "tool_use", "stop_sequence", "pause_turn"):
        return "completed", None
    if stop_reason == "max_tokens":
        return "incomplete", {"reason": "max_output_tokens"}
    if stop_reason == "refusal":
        return "incomplete", {"reason": "content_filter"}
    raise AssertionError(f"未覆盖的 stop_reason: {stop_reason!r}")


# ---------- Stream (Responses → IR) ----------


def responses_stream_to_ir(
    events: Iterable[dict[str, Any]],
) -> Iterator[StreamEvent]:
    """Responses SSE 事件流 → IR StreamEvent 流。

    状态:
    - `item_to_ir_idx`:Responses output_index → IR block index
    - `item_type`:同上 key,记录 item 是 message 还是 function_call
    - `text_seen_for_item`:message 类 item 是否已 emit 过 TextBlock start
    - `finalized`:是否已 emit `MessageDelta(stop_reason)`,用于决定最后是否补 MessageStop
    """
    started = False
    finalized = False
    item_to_ir_idx: dict[int, int] = {}
    item_type: dict[int, str] = {}
    text_block_opened: dict[int, bool] = {}
    next_ir_idx = 0
    last_id = ""
    last_model = ""

    for event in events:
        etype = event.get("type")

        if etype == "response.created" or etype == "response.in_progress":
            if not started:
                resp: Any = event.get("response") or {}
                if not isinstance(resp, dict):
                    raise ValueError("response.created.response 必须是 dict")
                r = cast(dict[str, Any], resp)
                last_id = str(r.get("id", ""))
                last_model = str(r.get("model", ""))
                yield MessageStartEvent(id=last_id, model=last_model, usage=Usage())
                started = True

        elif etype == "response.output_item.added":
            oidx_val = event.get("output_index")
            item_raw = event.get("item")
            if not isinstance(oidx_val, int):
                raise ValueError("response.output_item.added.output_index 必须是 int")
            if not isinstance(item_raw, dict):
                raise ValueError("response.output_item.added.item 必须是 dict")
            item = cast(dict[str, Any], item_raw)
            itype = item.get("type")

            ir_idx = next_ir_idx
            next_ir_idx += 1
            item_to_ir_idx[oidx_val] = ir_idx

            if itype == "function_call":
                item_type[oidx_val] = "function_call"
                call_id = item.get("call_id")
                name = item.get("name")
                if not isinstance(call_id, str):
                    raise ValueError("function_call.call_id 必须是 str")
                if not isinstance(name, str):
                    raise ValueError("function_call.name 必须是 str")
                yield BlockStartEvent(
                    index=ir_idx,
                    block=ToolUseBlock(id=call_id, name=name, input={}),
                )
            elif itype == "message":
                # message 类 item 的 BlockStart(TextBlock) 推迟到首个 output_text.delta
                # 看到时再 emit(避免空 message item 产生空 block)
                item_type[oidx_val] = "message"
                text_block_opened[oidx_val] = False
            else:
                raise ValueError(f"response.output_item.added 不支持的 item.type: {itype!r}")

        elif etype == "response.content_part.added":
            # v0.1 忽略此事件,真正的 block start 靠 output_text.delta 首次出现触发
            continue

        elif etype == "response.content_part.done":
            continue

        elif etype == "response.output_text.delta":
            oidx_val = event.get("output_index")
            if not isinstance(oidx_val, int):
                raise ValueError("output_text.delta.output_index 必须是 int")
            if oidx_val not in item_to_ir_idx:
                raise ValueError(
                    f"output_text.delta 对应 output_index {oidx_val} 未见 output_item.added"
                )
            ir_idx = item_to_ir_idx[oidx_val]
            if not text_block_opened.get(oidx_val, False):
                yield BlockStartEvent(index=ir_idx, block=TextBlock(text=""))
                text_block_opened[oidx_val] = True
            delta_val = event.get("delta")
            if not isinstance(delta_val, str):
                raise ValueError("output_text.delta.delta 必须是 str")
            yield TextDeltaEvent(index=ir_idx, text=delta_val)

        elif etype == "response.output_text.done":
            # 对应 block 在 output_item.done 一起关;本事件丢弃
            continue

        elif etype == "response.function_call_arguments.delta":
            oidx_val = event.get("output_index")
            if not isinstance(oidx_val, int):
                raise ValueError("function_call_arguments.delta.output_index 必须是 int")
            if oidx_val not in item_to_ir_idx:
                raise ValueError(
                    f"function_call_arguments.delta 对应 output_index {oidx_val} "
                    "未见 output_item.added"
                )
            ir_idx = item_to_ir_idx[oidx_val]
            delta_val = event.get("delta")
            if not isinstance(delta_val, str):
                raise ValueError("function_call_arguments.delta.delta 必须是 str")
            yield InputJsonDeltaEvent(index=ir_idx, partial_json=delta_val)

        elif etype == "response.function_call_arguments.done":
            continue

        elif etype == "response.output_item.done":
            oidx_val = event.get("output_index")
            if not isinstance(oidx_val, int):
                raise ValueError("output_item.done.output_index 必须是 int")
            if oidx_val not in item_to_ir_idx:
                raise ValueError(f"output_item.done 对应 output_index {oidx_val} 未见 added")
            ir_idx = item_to_ir_idx[oidx_val]
            # message 类 item 未产生 text_delta 时也不发 BlockStop(无 block 开启)
            if item_type.get(oidx_val) != "message" or text_block_opened.get(oidx_val, False):
                yield BlockStopEvent(index=ir_idx)

        elif etype == "response.completed":
            resp = event.get("response") or {}
            if not isinstance(resp, dict):
                raise ValueError("response.completed.response 必须是 dict")
            r = cast(dict[str, Any], resp)
            has_tool_use = any(
                isinstance(it, dict) and cast(dict[str, Any], it).get("type") == "function_call"
                for it in cast(list[Any], r.get("output") or [])
            )
            stop_reason = _derive_stop_reason(r, has_tool_use=has_tool_use)
            usage_raw = r.get("usage")
            usage_delta: UsageDelta | None = None
            if isinstance(usage_raw, dict):
                u = cast(dict[str, Any], usage_raw)
                usage_delta = UsageDelta(
                    input_tokens=u.get("input_tokens"),
                    output_tokens=u.get("output_tokens"),
                )
            yield MessageDeltaEvent(stop_reason=stop_reason, usage=usage_delta)
            finalized = True

        elif etype in ("response.incomplete", "response.failed"):
            # v0.1 统一视为终结,依赖 response 快照推断 stop_reason
            resp = event.get("response") or {}
            if not isinstance(resp, dict):
                raise ValueError(f"{etype}.response 必须是 dict")
            r = cast(dict[str, Any], resp)
            stop_reason = _derive_stop_reason(r, has_tool_use=False)
            yield MessageDeltaEvent(stop_reason=stop_reason)
            finalized = True

        elif etype == "response.error":
            err: Any = event.get("error") or {}
            if not isinstance(err, dict):
                raise ValueError("response.error.error 必须是 dict")
            e = cast(dict[str, Any], err)
            yield ErrorEvent(
                error_type=str(e.get("type", "api_error")),
                message=str(e.get("message", "")),
            )

        else:
            # 其余事件(如 reasoning_summary_text.delta / refusal.delta 等)v0.1 不翻译
            raise ValueError(f"不支持的 Responses 流事件: {etype!r}")

    if finalized:
        yield MessageStopEvent()


# ---------- Stream (IR → Responses) ----------


def ir_to_responses_stream(
    events: Iterable[StreamEvent],
) -> Iterator[dict[str, Any]]:
    """IR StreamEvent 流 → Responses SSE 事件流。"""
    last_id = ""
    last_model = ""
    # IR block index → (Responses output_index, item type)
    ir_to_output_idx: dict[int, int] = {}
    ir_to_item_type: dict[int, str] = {}
    # 记录每个 ir block 已累计的 text / arguments,用于生成 output_item.done 时重构完整 item
    text_buf: dict[int, list[str]] = {}
    args_buf: dict[int, list[str]] = {}
    # 记录 BlockStart 时的元信息
    tool_block_meta: dict[int, tuple[str, str]] = {}  # ir_idx → (call_id, name)
    next_output_idx = 0
    stop_reason_buf: StopReason | None = None
    # usage 累计:MessageStart 给 input_tokens,MessageDelta 给累计 output_tokens;
    # 最终塞进 response.completed 的快照(对齐非流路径的 usage 字段)
    input_tokens_buf = 0
    output_tokens_buf = 0

    for ev in events:
        if isinstance(ev, MessageStartEvent):
            last_id = ev.id
            last_model = ev.model
            input_tokens_buf = ev.usage.input_tokens
            output_tokens_buf = ev.usage.output_tokens
            yield {
                "type": "response.created",
                "response": _response_snapshot(last_id, last_model, output=[]),
            }
        elif isinstance(ev, BlockStartEvent):
            block = ev.block
            oidx = next_output_idx
            next_output_idx += 1
            ir_to_output_idx[ev.index] = oidx
            if isinstance(block, TextBlock):
                ir_to_item_type[ev.index] = "message"
                text_buf[ev.index] = []
                yield {
                    "type": "response.output_item.added",
                    "output_index": oidx,
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "status": "in_progress",
                    },
                }
            elif isinstance(block, ToolUseBlock):
                ir_to_item_type[ev.index] = "function_call"
                args_buf[ev.index] = []
                tool_block_meta[ev.index] = (block.id, block.name)
                yield {
                    "type": "response.output_item.added",
                    "output_index": oidx,
                    "item": {
                        "type": "function_call",
                        "call_id": block.id,
                        "name": block.name,
                        "arguments": "",
                        "status": "in_progress",
                    },
                }
            else:
                raise ValueError(f"Responses 流式不支持 block: {type(block).__name__}")
        elif isinstance(ev, TextDeltaEvent):
            oidx = ir_to_output_idx[ev.index]
            text_buf.setdefault(ev.index, []).append(ev.text)
            yield {
                "type": "response.output_text.delta",
                "output_index": oidx,
                "content_index": 0,
                "delta": ev.text,
            }
        elif isinstance(ev, InputJsonDeltaEvent):
            oidx = ir_to_output_idx[ev.index]
            args_buf.setdefault(ev.index, []).append(ev.partial_json)
            yield {
                "type": "response.function_call_arguments.delta",
                "output_index": oidx,
                "delta": ev.partial_json,
            }
        elif isinstance(ev, BlockStopEvent):
            oidx = ir_to_output_idx[ev.index]
            itype = ir_to_item_type.get(ev.index)
            if itype == "message":
                full_text = "".join(text_buf.get(ev.index, []))
                yield {
                    "type": "response.output_item.done",
                    "output_index": oidx,
                    "item": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": full_text}],
                        "status": "completed",
                    },
                }
            elif itype == "function_call":
                call_id, name = tool_block_meta[ev.index]
                full_args = "".join(args_buf.get(ev.index, []))
                yield {
                    "type": "response.output_item.done",
                    "output_index": oidx,
                    "item": {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": full_args,
                        "status": "completed",
                    },
                }
            else:
                raise AssertionError(f"未覆盖的 item type: {itype!r}")
        elif isinstance(ev, MessageDeltaEvent):
            # 缓存 stop_reason + usage(Anthropic 的 output_tokens 是累计值),
            # 等 MessageStop 时一并塞进 response.completed 快照
            stop_reason_buf = ev.stop_reason or stop_reason_buf
            if ev.usage is not None and ev.usage.output_tokens is not None:
                output_tokens_buf = ev.usage.output_tokens
        elif isinstance(ev, MessageStopEvent):
            status, incomplete_details = _stop_reason_to_status(stop_reason_buf)
            resp = _response_snapshot(last_id, last_model, output=[])
            resp["status"] = status
            resp["usage"] = {
                "input_tokens": input_tokens_buf,
                "output_tokens": output_tokens_buf,
                "total_tokens": input_tokens_buf + output_tokens_buf,
            }
            if incomplete_details is not None:
                resp["incomplete_details"] = incomplete_details
            final_type = "response.completed" if status == "completed" else "response.incomplete"
            yield {"type": final_type, "response": resp}
        elif isinstance(ev, PingEvent):
            continue
        elif isinstance(ev, ErrorEvent):
            yield {
                "type": "response.error",
                "error": {"type": ev.error_type, "message": ev.message},
            }
        else:
            # union 穷尽:narrow 到 ThinkingDeltaEvent | SignatureDeltaEvent(v0.1 不支持)
            raise ValueError(f"Responses 流式 v0.1 不支持事件: {type(ev).__name__}")


def _response_snapshot(id_: str, model: str, output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": id_,
        "object": "response",
        "created_at": 0,
        "model": model,
        "output": output,
        "status": "in_progress",
    }
