"""翻译层:外部格式(messages/completions/responses)↔ IR ↔ 上游。

子包:
- `ir`:与格式无关的中间表示(Pydantic 模型)
- `messages/`:Anthropic Messages API 方向的 adapter(阶段 2.1)
- `completions/`:OpenAI Chat Completions adapter(阶段 2.2)
- `responses/`:OpenAI Responses adapter(阶段 2.5)

子包命名与 `rosetta.shared.formats.Protocol` 枚举值一一对齐。
"""
