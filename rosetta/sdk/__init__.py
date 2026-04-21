"""rosetta SDK:发现/启动 server + 封装管理面 + 数据面 chat。

入口
----
- `ProxyClient.discover_session()`:连到本机 server(不在就自动 spawn)
- `ProxyClient.direct_session()`:绕 server 直连上游(BYOK)
- `chat_once(...)`:发一条消息拿 `ChatResult`
- `iter_text_deltas(resp, fmt)`:三格式 SSE → 文本增量
"""

from __future__ import annotations

from rosetta.sdk.chat import ChatResult, chat_once
from rosetta.sdk.client import ProxyClient
from rosetta.sdk.discover import discover
from rosetta.sdk.streams import iter_text_deltas

__all__ = [
    "ChatResult",
    "ProxyClient",
    "chat_once",
    "discover",
    "iter_text_deltas",
]
