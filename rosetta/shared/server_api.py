"""三种内置 server_api 标识 + 固定路径映射。

`base_url` / `upstreams.base_url` 表示上游 API 前缀,可以包含网关或反代路径;
具体 endpoint 始终由 `ServerApi` 决定并在这里统一追加。
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


def upstream_endpoint_url(base_url: str, server_api: ServerApi) -> str:
    """Return the concrete upstream endpoint for an API prefix and protocol.

    `base_url` may already include `/v1`, matching OpenAI SDK convention. In that
    case only append the API-specific tail to avoid `/v1/v1/...`.
    """
    prefix = base_url.rstrip("/")
    path = SERVER_API_PATHS[server_api]
    if prefix.endswith("/v1") and path.startswith("/v1/"):
        path = path.removeprefix("/v1")
    return prefix + path
