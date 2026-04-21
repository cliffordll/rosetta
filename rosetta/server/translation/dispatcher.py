"""翻译分派器:按 (client_format, upstream_format) 选择 adapter 路径。

职责
----
1. **非流式请求翻译**:client body → IR(输入 adapter) → upstream body(输出 adapter)
2. **非流式响应翻译**:upstream body → IR(输出 adapter) → client body(输入 adapter)
3. **格式一致短路**:同格式直通时 IR 过一遍再 dump,仍用翻译路径以便统一校验 / 脱敏
   (开销极小,换来所有路径都走 Pydantic 严格校验的一致性)

流式翻译由 `stream.py` 编排;本模块只管非流式。

Format 枚举(沿用 `rosetta.shared.formats.Format`):
- `MESSAGES`:Anthropic /v1/messages
- `CHAT_COMPLETIONS`:OpenAI /v1/chat/completions
- `RESPONSES`:OpenAI /v1/responses
"""

from __future__ import annotations

from typing import Any

from rosetta.server.translation.completions.request import (
    completions_to_ir,
    ir_to_completions,
)
from rosetta.server.translation.completions.response import (
    completions_response_to_ir,
    ir_to_completions_response,
)
from rosetta.server.translation.ir import RequestIR, ResponseIR
from rosetta.server.translation.messages.request import (
    ir_to_messages,
    messages_to_ir,
)
from rosetta.server.translation.messages.response import (
    ir_to_messages_response,
    messages_response_to_ir,
)
from rosetta.server.translation.responses.request import (
    ir_to_responses,
    responses_to_ir,
)
from rosetta.server.translation.responses.response import (
    ir_to_responses_response,
    responses_response_to_ir,
)
from rosetta.shared.formats import Format

# Adapter 表:分派用,保持形式上对称便于后续扩展
_REQ_TO_IR = {
    Format.MESSAGES: messages_to_ir,
    Format.CHAT_COMPLETIONS: completions_to_ir,
    Format.RESPONSES: responses_to_ir,
}
_IR_TO_REQ = {
    Format.MESSAGES: ir_to_messages,
    Format.CHAT_COMPLETIONS: ir_to_completions,
    Format.RESPONSES: ir_to_responses,
}
_RESP_TO_IR = {
    Format.MESSAGES: messages_response_to_ir,
    Format.CHAT_COMPLETIONS: completions_response_to_ir,
    Format.RESPONSES: responses_response_to_ir,
}
_IR_TO_RESP = {
    Format.MESSAGES: ir_to_messages_response,
    Format.CHAT_COMPLETIONS: ir_to_completions_response,
    Format.RESPONSES: ir_to_responses_response,
}


def translate_request(
    body: dict[str, Any], *, source: Format, target: Format
) -> tuple[RequestIR, dict[str, Any]]:
    """客户端请求 body → (IR, 上游请求 body)。

    返回 tuple 便于调用方同时拿到 IR(用于日志 / 度量)和上游 body(用于转发)。
    `source == target` 时仍走 IR,作为统一校验通道。
    """
    ir = _REQ_TO_IR[source](body)
    upstream_body = _IR_TO_REQ[target](ir)
    return ir, upstream_body


def translate_response(
    body: dict[str, Any], *, source: Format, target: Format
) -> tuple[ResponseIR, dict[str, Any]]:
    """上游响应 body → (IR, 客户端响应 body)。

    `source` 是上游的 format,`target` 是客户端的 format。
    """
    ir = _RESP_TO_IR[source](body)
    client_body = _IR_TO_RESP[target](ir)
    return ir, client_body
