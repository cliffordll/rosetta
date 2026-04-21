"""OpenAI Responses API 格式 ↔ IR adapter(阶段 2.5.1)。

Responses API 是 OpenAI 的新一代有状态 API(`/v1/responses`),覆盖 v0.1 的范围
---------------------------------------------------------------------------

支持(近似 Chat Completions 的功能子集 + Responses 的表达方式)
- Request:`model` / `input`(str 或 item 数组) / `instructions`(≈ system)
  / `max_output_tokens`(≈ max_tokens) / `temperature` / `top_p`
  / `tools`(function 类型) / `tool_choice` / `stream`
- Input items 支持:
  - `{"type":"message","role":"user|assistant|system", "content":[...]}`
    - content parts:`input_text`(user/system) / `output_text`(assistant)
  - `{"type":"function_call","call_id":...,"name":...,"arguments":"json-str"}`
    - assistant 侧的工具调用,对应 IR `ToolUseBlock`(id ≡ call_id)
  - `{"type":"function_call_output","call_id":...,"output":...}`
    - 工具返回,对应 IR `ToolResultBlock`(挂载到后续 user 或独立一条 user)
- Response:`id` / `model` / `output[]`(message 或 function_call) / `status`
  / `incomplete_details`(映射 stop_reason) / `usage`
- Stream:Response-specific 事件(`response.created` /
  `response.output_item.added` / `response.output_text.delta` /
  `response.function_call_arguments.delta` / `response.completed` 等)
  ↔ IR StreamEvent

有状态特性(v0.1 不支持,统一由 degradation 层处理)
- `store=True`:忽略 + `x-rosetta-warnings: store_ignored`
- `previous_response_id`:非 Responses 上游返回 400 `stateful_not_translatable`
- `background=True`:同上
- 内置 tools(`web_search` / `file_search` / `computer_use`):
  剥除 + `x-rosetta-warnings: builtin_tools_removed:<name>`

其余不支持字段(raise)
- `parallel_tool_calls` / `reasoning` / `metadata` / `include`
- 多模态 input parts(`input_image` / `input_audio` 等)
"""
