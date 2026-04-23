"""ProxyClient admin 方法测试(4.1 · SDK)。

用 `httpx.MockTransport` 拦截请求,覆盖:
- list_upstreams / create_upstream / delete_upstream
- list_logs
- stats
- shutdown
- direct 模式下 admin 方法必须抛 RuntimeError
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio

from rosetta.sdk.client import ProxyClient
from rosetta.server.controller.upstreams import UpstreamCreate


def _make_client_with_handler(
    handler: httpx.MockTransport | None = None,
) -> tuple[ProxyClient, dict[str, Any]]:
    """构造 server 模式的 ProxyClient;transport 不给则产一个回显 handler。"""
    captured: dict[str, Any] = {"request": None}

    def _dispatch(req: httpx.Request) -> httpx.Response:
        captured["request"] = req
        return httpx.Response(200, json={})

    transport = handler if handler is not None else httpx.MockTransport(_dispatch)
    http = httpx.AsyncClient(transport=transport)
    client = ProxyClient(http=http, base_url="http://127.0.0.1:12345", mode="server")
    return client, captured


@pytest_asyncio.fixture
async def echo_client() -> AsyncIterator[tuple[ProxyClient, dict[str, Any]]]:
    captured: dict[str, Any] = {"request": None, "response": httpx.Response(200, json={})}

    def _dispatch(req: httpx.Request) -> httpx.Response:
        captured["request"] = req
        return captured["response"]

    transport = httpx.MockTransport(_dispatch)
    http = httpx.AsyncClient(transport=transport)
    client = ProxyClient(http=http, base_url="http://127.0.0.1:12345", mode="server")
    try:
        yield client, captured
    finally:
        await http.aclose()


# ---------- ping / status ----------


async def test_ping_true(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"ok": True})
    assert await client.ping() is True
    assert captured["request"].url.path == "/admin/ping"


async def test_ping_false_on_non_200(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(503, json={})
    assert await client.ping() is False


async def test_status(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={"version": "0.1.0", "uptime_ms": 12345, "upstreams_count": 2},
    )
    status = await client.status()
    assert status.version == "0.1.0"
    assert status.uptime_ms == 12345
    assert status.upstreams_count == 2
    assert captured["request"].url.path == "/admin/status"


# ---------- upstreams ----------


async def test_list_upstreams(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json=[
            {
                "id": "some-id",
                "name": "ant",
                "protocol": "messages",
                "provider": "anthropic",
                "base_url": "https://api.anthropic.com",
                "enabled": True,
                "created_at": datetime(2026, 4, 22, 10, 0, 0).isoformat(),
            }
        ],
    )
    upstreams = await client.list_upstreams()
    assert len(upstreams) == 1
    assert upstreams[0].name == "ant"
    assert captured["request"].method == "GET"
    assert captured["request"].url.path == "/admin/upstreams"


async def test_create_upstream(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        201,
        json={
            "id": "new-id",
            "name": "ant-new",
            "protocol": "messages",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "enabled": True,
            "created_at": "2026-04-22T10:00:00",
        },
    )
    payload = UpstreamCreate(
        name="ant-new",
        protocol="messages",
        provider="anthropic",
        api_key="sk-xxx",
        base_url="https://api.anthropic.com",
    )
    created = await client.create_upstream(payload)
    assert created.id == "new-id"
    req = captured["request"]
    assert req.method == "POST"
    assert req.url.path == "/admin/upstreams"
    import json as _json
    sent = _json.loads(req.content)
    assert sent["name"] == "ant-new"
    assert sent["api_key"] == "sk-xxx"


async def test_delete_upstream_on_204(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(204)
    await client.delete_upstream("some-id")
    req = captured["request"]
    assert req.method == "DELETE"
    assert req.url.path == "/admin/upstreams/some-id"


async def test_delete_upstream_not_found_raises(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(404, json={"detail": "not found"})
    with pytest.raises(httpx.HTTPStatusError):
        await client.delete_upstream("ghost")


# ---------- logs / stats / shutdown ----------


async def test_list_logs_with_filters(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json=[])
    await client.list_logs(limit=5, offset=10, upstream="ant")
    req = captured["request"]
    assert req.url.params["limit"] == "5"
    assert req.url.params["offset"] == "10"
    assert req.url.params["upstream"] == "ant"


async def test_stats(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "period": "today",
            "since": "2026-04-22T00:00:00+00:00",
            "total_requests": 100,
            "success_rate": 0.95,
            "avg_latency_ms": 412.5,
        },
    )
    stats = await client.stats(period="today")
    assert stats.total_requests == 100
    assert stats.success_rate == 0.95
    req = captured["request"]
    assert req.url.path == "/admin/stats"
    assert req.url.params["period"] == "today"


async def test_shutdown(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"ok": True})
    await client.shutdown()
    req = captured["request"]
    assert req.method == "POST"
    assert req.url.path == "/admin/shutdown"


# ---------- direct 模式下 admin 方法应 raise ----------


async def test_direct_mode_blocks_admin_methods() -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    client = ProxyClient(
        http=http,
        base_url="https://api.anthropic.com",
        mode="direct",
        _direct_api_key="sk",
    )
    try:
        for method_name in (
            "ping",
            "status",
            "list_upstreams",
            "shutdown",
        ):
            with pytest.raises(RuntimeError, match="direct 模式不支持 admin 操作"):
                await getattr(client, method_name)()
    finally:
        await http.aclose()
