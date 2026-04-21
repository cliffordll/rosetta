"""Anthropic Messages API ↔ IR adapter。

- `request.py`:`messages_to_ir` / `ir_to_messages`
- `response.py`:非流 `messages_response_to_ir` / `ir_to_messages_response`,
  流式 `messages_stream_to_ir` / `ir_to_messages_stream`(阶段 2.1b)
"""
