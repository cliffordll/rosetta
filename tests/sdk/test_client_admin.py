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
from rosetta.server.controller.upstreams import UpstreamCreate, UpstreamUpdate
from rosetta.shared.server_api import ServerApi


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
        json={
            "version": "0.1.0",
            "uptime_ms": 12345,
            "upstreams_count": 2,
            "url": "http://127.0.0.1:12345",
        },
    )
    status = await client.status()
    assert status.version == "0.1.0"
    assert status.uptime_ms == 12345
    assert status.upstreams_count == 2
    assert status.url == "http://127.0.0.1:12345"
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
                "native_api": "messages",
                "provider": "anthropic",
                "base_url": "https://api.anthropic.com",
                "enabled": True,
                "model": None,
                "created_at": datetime(2026, 4, 22, 10, 0, 0).isoformat(),
            }
        ],
    )
    upstreams = await client.list_upstreams()
    assert len(upstreams) == 1
    assert upstreams[0].name == "ant"
    assert captured["request"].method == "GET"
    assert captured["request"].url.path == "/admin/upstreams"


async def test_list_model_defaults(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"gpt-4o": "u1"})

    defaults = await client.list_model_defaults()

    assert defaults == {"gpt-4o": "u1"}
    assert captured["request"].method == "GET"
    assert captured["request"].url.path == "/admin/upstreams/model-defaults"


async def test_test_upstream(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "ok": True,
            "upstream_id": "u1",
            "upstream_name": "oai",
            "native_api": "completions",
            "status_code": 200,
            "category": "ok",
            "summary": "request succeeded",
            "detail": None,
        },
    )

    result = await client.test_upstream("u1")

    assert result.ok is True
    assert result.upstream_id == "u1"
    assert result.category == "ok"
    assert captured["request"].method == "POST"
    assert captured["request"].url.path == "/admin/upstreams/u1/test"


async def test_get_logs_config(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"log_content": "summary", "page_size": 20})
    config = await client.logs_config()
    assert config.log_content == "summary"
    assert config.page_size == 20
    assert captured["request"].url.path == "/admin/logs/config"


async def test_update_logs_config(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"log_content": "full", "page_size": 50})
    config = await client.update_logs_config(log_content="full", page_size=50)
    assert config.log_content == "full"
    assert config.page_size == 50
    assert captured["request"].method == "PUT"
    assert captured["request"].url.path == "/admin/logs/config"


async def test_clear_logs(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"deleted": 3})

    deleted = await client.clear_logs()

    assert deleted == 3
    assert captured["request"].method == "DELETE"
    assert captured["request"].url.path == "/admin/logs"


def test_server_data_headers_use_x_api_key_for_messages_override() -> None:
    client, _ = _make_client_with_handler()

    _, headers = client.data_url_and_headers(
        server_api=ServerApi.MESSAGES,
        override_api_key="sk-override",
    )

    assert headers["x-api-key"] == "sk-override"
    assert "authorization" not in headers


def test_server_data_headers_use_authorization_for_completions_override() -> None:
    client, _ = _make_client_with_handler()

    _, headers = client.data_url_and_headers(
        server_api=ServerApi.CHAT_COMPLETIONS,
        override_api_key="sk-override",
    )

    assert headers["authorization"] == "Bearer sk-override"
    assert "x-api-key" not in headers


def test_direct_data_url_allows_base_url_with_path_prefix() -> None:
    client = ProxyClient(
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        base_url="https://gateway.example.com/proxy/openai",
        mode="direct",
        _direct_api_key="sk",
    )

    url, _ = client.data_url_and_headers(server_api=ServerApi.CHAT_COMPLETIONS)

    assert url == "https://gateway.example.com/proxy/openai/v1/chat/completions"


async def test_create_upstream(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        201,
        json={
            "id": "new-id",
            "name": "ant-new",
            "native_api": "messages",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "enabled": True,
            "model": None,
            "created_at": "2026-04-22T10:00:00",
        },
    )
    payload = UpstreamCreate(
        name="ant-new",
        native_api="messages",
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


async def test_update_upstream(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "id": "p1-id",
            "name": "renamed",
            "native_api": "messages",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "enabled": True,
            "model": "claude-sonnet-4-5",
            "created_at": "2026-04-22T10:00:00",
        },
    )
    payload = UpstreamUpdate(name="renamed", model="claude-sonnet-4-5")
    updated = await client.update_upstream("p1-id", payload)
    assert updated.name == "renamed"
    req = captured["request"]
    assert req.method == "PUT"
    assert req.url.path == "/admin/upstreams/p1-id"
    import json as _json

    sent = _json.loads(req.content)
    # exclude_unset:只发用户传的字段(name + model),不发其他
    assert set(sent.keys()) == {"name", "model"}


async def test_set_model_default_upstream(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "id": "p1-id",
            "name": "p1",
            "native_api": "messages",
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "enabled": True,
            "model": "gpt-4o",
            "created_at": "2026-04-22T10:00:00",
        },
    )

    updated = await client.set_model_default_upstream("p1-id", model="gpt-4o")

    assert updated.name == "p1"
    req = captured["request"]
    assert req.method == "PUT"
    assert req.url.path == "/admin/upstreams/p1-id/model-default"
    assert req.url.params["model"] == "gpt-4o"


# ---------- logs / stats / shutdown ----------


async def test_list_logs_with_filters(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(200, json={"items": [], "total": 0})
    result = await client.list_logs(limit=5, offset=10, upstream="u1")
    assert result.items == []
    assert result.total == 0
    req = captured["request"]
    assert req.url.params["limit"] == "5"
    assert req.url.params["offset"] == "10"
    assert req.url.params["upstream"] == "u1"


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


# ---------- chat config ----------


async def test_chat_config_get(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={"max_tokens": 4096, "stream": False},
    )
    config = await client.chat_config()
    assert config.max_tokens == 4096
    assert config.stream is False
    req = captured["request"]
    assert req.method == "GET"
    assert req.url.path == "/admin/chat/config"


async def test_chat_config_get_defaults(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={"max_tokens": 8192, "stream": True},
    )
    config = await client.chat_config()
    assert config.max_tokens == 8192
    assert config.stream is True


async def test_chat_config_update_max_tokens(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={"max_tokens": 2048, "stream": True},
    )
    config = await client.update_chat_config(max_tokens=2048)
    assert config.max_tokens == 2048
    assert config.stream is True
    req = captured["request"]
    assert req.method == "PUT"
    assert req.url.path == "/admin/chat/config"
    import json as _json

    sent = _json.loads(req.content)
    assert sent == {"max_tokens": 2048}


async def test_chat_config_update_stream(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={"max_tokens": 8192, "stream": False},
    )
    config = await client.update_chat_config(stream=False)
    assert config.max_tokens == 8192
    assert config.stream is False
    req = captured["request"]
    assert req.method == "PUT"
    assert req.url.path == "/admin/chat/config"
    import json as _json

    sent = _json.loads(req.content)
    assert sent == {"stream": False}


async def test_chat_config_update_both(
    echo_client: tuple[ProxyClient, dict[str, Any]],
) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={"max_tokens": 4096, "stream": False},
    )
    config = await client.update_chat_config(max_tokens=4096, stream=False)
    assert config.max_tokens == 4096
    assert config.stream is False
    req = captured["request"]
    assert req.method == "PUT"
    assert req.url.path == "/admin/chat/config"
    import json as _json

    sent = _json.loads(req.content)
    assert sent == {"max_tokens": 4096, "stream": False}


async def test_chat_config_direct_mode_raises() -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    client = ProxyClient(
        http=http,
        base_url="https://api.anthropic.com",
        mode="direct",
        _direct_api_key="sk",
    )
    try:
        with pytest.raises(RuntimeError, match="direct 模式不支持 admin 操作"):
            await client.chat_config()
        with pytest.raises(RuntimeError, match="direct 模式不支持 admin 操作"):
            await client.update_chat_config(max_tokens=4096)
    finally:
        await http.aclose()


async def test_setup_preview(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "target": "codex",
            "path": "C:/Users/me/.codex/config.toml",
            "exists": True,
            "original": "old",
            "generated": "new",
            "language": "toml",
            "backup_path": None,
        },
    )

    result = await client.setup_preview("codex", upstream_id="u1")

    assert result.target == "codex"
    assert result.original == "old"
    assert result.generated == "new"
    assert captured["request"].method == "GET"
    assert captured["request"].url.path == "/admin/setup/codex/preview"
    assert captured["request"].url.params["upstream_id"] == "u1"


async def test_setup_apply(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "target": "claude",
            "path": "C:/Users/me/.claude/settings.json",
            "exists": True,
            "original": "old",
            "generated": "new",
            "language": "json",
            "backup_path": "C:/Users/me/.claude/settings.json.bak-20260625-153000",
        },
    )

    result = await client.setup_apply("claude", upstream_id="u1")

    assert result.target == "claude"
    assert result.backup_path == "C:/Users/me/.claude/settings.json.bak-20260625-153000"
    assert captured["request"].method == "POST"
    assert captured["request"].url.path == "/admin/setup/claude/apply"
    assert captured["request"].read() == b'{"upstream_id":"u1"}'


async def test_setup_clear(echo_client: tuple[ProxyClient, dict[str, Any]]) -> None:
    client, captured = echo_client
    captured["response"] = httpx.Response(
        200,
        json={
            "target": "codex",
            "path": "C:/Users/me/.codex/config.toml",
            "exists": True,
            "original": "old",
            "generated": "new",
            "language": "toml",
            "backup_path": "C:/Users/me/.codex/config.toml.bak-20260625-153000",
        },
    )

    result = await client.setup_clear("codex")

    assert result.target == "codex"
    assert result.backup_path == "C:/Users/me/.codex/config.toml.bak-20260625-153000"
    assert captured["request"].method == "POST"
    assert captured["request"].url.path == "/admin/setup/codex/clear"
