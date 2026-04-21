"""三格式标识 + 上游路径映射 + provider type 默认 base_url 表。

定义:
- `Format`:API 形态(/v1/messages / /v1/chat/completions / /v1/responses)
- `UPSTREAM_PATH`:format → 上游 URL 路径(同格式直通:format 是啥就打啥路径)
- `DEFAULT_BASE_URL`:provider.type → 官方上游 base_url(DB 里 base_url 为空时兜底)

阶段 1.3 只走"同格式直通",format 和 provider.type 的交叉翻译要到阶段 2。
"""

from __future__ import annotations

from enum import StrEnum


class Format(StrEnum):
    MESSAGES = "messages"
    CHAT_COMPLETIONS = "completions"
    RESPONSES = "responses"


UPSTREAM_PATH: dict[Format, str] = {
    Format.MESSAGES: "/v1/messages",
    Format.CHAT_COMPLETIONS: "/v1/chat/completions",
    Format.RESPONSES: "/v1/responses",
}


# provider.type → 官方 base_url(建 provider 时 base_url 留空就取这里;对齐 DESIGN.md §8.2 表格)
DEFAULT_BASE_URL: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "openrouter": "https://openrouter.ai/api",
    # custom 必须显式填写,不在这里兜底
}
