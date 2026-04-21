"""翻译层中间表示(IR)。

v0.1 策略:IR 形状几乎是 Anthropic Messages API 的镜像(见 DESIGN.md 对应讨论),
Claude adapter 做近 identity 映射;跨到 OpenAI 格式时再在 adapter 里做字段名 / 结构对齐。

若后续发现系统性字段错配,再重构 IR 为更中立的形状(不提前抽象)。

覆盖范围:
- Content block:text / thinking / redacted_thinking / tool_use / tool_result
- Request / Response 主干字段
- Stream Event(阶段 2.1b 流式 roundtrip 会用到;跨格式状态机到阶段 2.4)
- Image block v0.1 不做
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------- Content Blocks ----------


class _StrictBase(BaseModel):
    """所有 IR 模型的基类:禁止未声明字段,避免静默吞下未翻译字段。"""

    model_config = ConfigDict(extra="forbid")


class TextBlock(_StrictBase):
    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(_StrictBase):
    type: Literal["thinking"] = "thinking"
    thinking: str
    # Anthropic extended thinking:assistant 回填时 signature 必须原样保留,否则上游 400
    signature: str | None = None


class RedactedThinkingBlock(_StrictBase):
    type: Literal["redacted_thinking"] = "redacted_thinking"
    # 上游加密的 thinking,内容不可读但必须原样回填
    data: str


class ToolUseBlock(_StrictBase):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(_StrictBase):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    # v0.1 支持 str 或 list[TextBlock];Image 嵌套留给 v1+
    content: str | list[TextBlock]
    # None = 字段缺失 = Anthropic 默认的 false,避免 dump 出幽灵字段
    is_error: bool | None = None


ContentBlock = Annotated[
    TextBlock | ThinkingBlock | RedactedThinkingBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]


# ---------- Messages / System ----------


class Message(_StrictBase):
    role: Literal["user", "assistant"]
    content: list[ContentBlock]


# system 可能是字符串,也可能是 list[TextBlock](Anthropic 允许 system 带 cache_control 等)
SystemPrompt = str | list[TextBlock]


# ---------- Tools ----------


class Tool(_StrictBase):
    name: str
    description: str | None = None
    input_schema: dict[str, Any]


class ToolChoiceAuto(_StrictBase):
    type: Literal["auto"] = "auto"
    disable_parallel_tool_use: bool | None = None


class ToolChoiceAny(_StrictBase):
    type: Literal["any"] = "any"
    disable_parallel_tool_use: bool | None = None


class ToolChoiceTool(_StrictBase):
    type: Literal["tool"] = "tool"
    name: str
    disable_parallel_tool_use: bool | None = None


class ToolChoiceNone(_StrictBase):
    type: Literal["none"] = "none"


ToolChoice = Annotated[
    ToolChoiceAuto | ToolChoiceAny | ToolChoiceTool | ToolChoiceNone,
    Field(discriminator="type"),
]


# ---------- Extended thinking config ----------


class ThinkingConfigEnabled(_StrictBase):
    type: Literal["enabled"] = "enabled"
    budget_tokens: int


class ThinkingConfigDisabled(_StrictBase):
    type: Literal["disabled"] = "disabled"


ThinkingConfig = Annotated[
    ThinkingConfigEnabled | ThinkingConfigDisabled,
    Field(discriminator="type"),
]


# ---------- Request / Response ----------


class RequestIR(_StrictBase):
    model: str
    messages: list[Message]
    system: SystemPrompt | None = None
    tools: list[Tool] | None = None
    tool_choice: ToolChoice | None = None
    max_tokens: int
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] | None = None
    metadata: dict[str, Any] | None = None
    thinking: ThinkingConfig | None = None
    # None 等价于字段缺失(Anthropic 默认非流),避免 dump 出 `"stream": false` 幽灵字段
    stream: bool | None = None


class Usage(_StrictBase):
    """主用 Usage:non-stream response 和 stream message_start 都是完整字段。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


class UsageDelta(_StrictBase):
    """流式 `message_delta` 事件专用的 Usage:Anthropic 只下发 `output_tokens`(累计),
    `input_tokens` 等字段通常缺失。所有字段 Optional,roundtrip 时剥 None 保持纯净。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


# Anthropic stop_reason 集合;跨格式翻译时在 adapter 里做枚举映射
StopReason = Literal[
    "end_turn",
    "max_tokens",
    "stop_sequence",
    "tool_use",
    "pause_turn",
    "refusal",
]


class ResponseIR(_StrictBase):
    id: str
    model: str
    role: Literal["assistant"] = "assistant"
    content: list[ContentBlock]
    stop_reason: StopReason | None = None
    stop_sequence: str | None = None
    usage: Usage


# ---------- Stream Events ----------
#
# 流式事件 IR:覆盖 Anthropic SSE 的全部事件种类,阶段 2.1b 用;
# 跨格式状态机到阶段 2.4 在 translation/stream.py 里接入。


class MessageStartEvent(_StrictBase):
    type: Literal["message_start"] = "message_start"
    id: str
    model: str
    usage: Usage


# BlockStart 的 block 带元信息:text/thinking 为空字符串;tool_use 的 input 为空 dict
StreamBlockStartBlock = Annotated[
    TextBlock | ThinkingBlock | RedactedThinkingBlock | ToolUseBlock,
    Field(discriminator="type"),
]


class BlockStartEvent(_StrictBase):
    type: Literal["content_block_start"] = "content_block_start"
    index: int
    block: StreamBlockStartBlock


class TextDeltaEvent(_StrictBase):
    type: Literal["text_delta"] = "text_delta"
    index: int
    text: str


class ThinkingDeltaEvent(_StrictBase):
    type: Literal["thinking_delta"] = "thinking_delta"
    index: int
    thinking: str


class SignatureDeltaEvent(_StrictBase):
    type: Literal["signature_delta"] = "signature_delta"
    index: int
    signature: str


class InputJsonDeltaEvent(_StrictBase):
    type: Literal["input_json_delta"] = "input_json_delta"
    index: int
    partial_json: str


class BlockStopEvent(_StrictBase):
    type: Literal["content_block_stop"] = "content_block_stop"
    index: int


class MessageDeltaEvent(_StrictBase):
    type: Literal["message_delta"] = "message_delta"
    stop_reason: StopReason | None = None
    stop_sequence: str | None = None
    # Anthropic 在 message_delta 里下发累计 output_tokens;用专门的宽松模型避免 roundtrip 噪音
    usage: UsageDelta | None = None


class MessageStopEvent(_StrictBase):
    type: Literal["message_stop"] = "message_stop"


class PingEvent(_StrictBase):
    type: Literal["ping"] = "ping"


class ErrorEvent(_StrictBase):
    type: Literal["error"] = "error"
    error_type: str
    message: str


StreamEvent = Annotated[
    MessageStartEvent
    | BlockStartEvent
    | TextDeltaEvent
    | ThinkingDeltaEvent
    | SignatureDeltaEvent
    | InputJsonDeltaEvent
    | BlockStopEvent
    | MessageDeltaEvent
    | MessageStopEvent
    | PingEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
