"""OpenAI Chat Completions 格式 ↔ IR adapter(阶段 2.2)。

v0.1 策略:对 Chat Completions 支持的字段子集做双向翻译;未覆盖字段一律 raise,
显式暴露未支持的能力(与 IR `extra="forbid"` 的严格哲学一致)。

覆盖范围
---------
- Request:`model` / `messages` / `tools` / `tool_choice` / `max_tokens`
  / `temperature` / `top_p` / `stop` / `stream`
- Non-stream response:`id` / `model` / `choices[0].message`(text + tool_calls)
  / `finish_reason` / `usage`(prompt_tokens ↔ input_tokens)
- Stream response:OpenAI chunk ↔ Anthropic 风 IR 事件的状态机
  (首个带 role 的 chunk → `MessageStart`;`delta.content` → `TextBlock`;
   `delta.tool_calls[]` → `ToolUseBlock` + `InputJsonDelta`;
   `finish_reason` → `MessageDelta` + `MessageStop`)

不支持(raise)
---------------
- Request 侧:`stream_options` / `n` / `seed` / `logprobs` / `logit_bias`
  / `presence_penalty` / `frequency_penalty` / `response_format` / `user`
  / `store` / `parallel_tool_calls` / `tools[].function.strict`
  / `image_url` / `audio` 等 content part
- IR→OpenAI 方向遇到 `top_k` / `thinking` / `metadata` / 多条 `system` 也 raise
- Response 侧:`choices` 数量不为 1(n>1 场景 v0.1 不做)

元信息字段(adapter 无法 roundtrip)
-----------------------------------
`created` / `system_fingerprint` / `service_tier` 等"响应一次性元信息",
adapter 在 dump 时用占位值生成,roundtrip 测试在对比前剥掉
(与 IR 的信息语义等价性无关)。
"""
