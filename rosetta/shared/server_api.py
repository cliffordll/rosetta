"""三种内置 server_api 标识 + 默认路径映射。

DB 的 `api_types` 表保存 API 类型 name → HTTP path。这里保留默认映射,
用于测试和表未加载时的兜底。
"""

from __future__ import annotations

from enum import StrEnum


class ServerApi(StrEnum):
    MESSAGES = "messages"
    CHAT_COMPLETIONS = "completions"
    RESPONSES = "responses"


DEFAULT_SERVER_API_PATHS: dict[str, str] = {
    ServerApi.MESSAGES.value: "/v1/messages",
    ServerApi.CHAT_COMPLETIONS.value: "/v1/chat/completions",
    ServerApi.RESPONSES.value: "/v1/responses",
}

SERVER_API_PATHS: dict[ServerApi, str] = {
    ServerApi.MESSAGES: "/v1/messages",
    ServerApi.CHAT_COMPLETIONS: "/v1/chat/completions",
    ServerApi.RESPONSES: "/v1/responses",
}
