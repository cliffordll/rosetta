"""/admin/* 管理端点测试(阶段 1.2 / 3.1)。

覆盖:
- GET /admin/upstreams:空 / 非空
- POST /admin/upstreams:成功(201)· name 冲突(409)· 不支持的 type(422)
- DELETE /admin/upstreams/{id}:成功(204)· 不存在(404)
- GET /admin/ping / /admin/status:基本心跳

用 httpx.AsyncClient + ASGITransport 做带 async session 的路由测试;依赖覆盖
`get_session` 直接注入 per-test 的 sqlite session。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.controller import admin_router
from rosetta.server.database.models import Upstream
from rosetta.server.database.session import get_session
from rosetta.server.service.forwarder import forwarder


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(admin_router, prefix="/admin")

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


# ---------- ping / status ----------


async def test_ping(client: AsyncClient) -> None:
    r = await client.get("/admin/ping")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_status(client: AsyncClient) -> None:
    r = await client.get("/admin/status")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body
    assert "uptime_ms" in body
    # migration seed 了一条 name=mock 的内置上游,全新 DB 就是 1
    assert body["upstreams_count"] == 1


async def test_logs_config_defaults(client: AsyncClient) -> None:
    r = await client.get("/admin/logs/config")
    assert r.status_code == 200
    assert r.json() == {"log_content": "summary", "page_size": 20}


async def test_logs_config_update(client: AsyncClient) -> None:
    r = await client.put(
        "/admin/logs/config",
        json={"log_content": "full", "page_size": 50},
    )
    assert r.status_code == 200
    assert r.json() == {"log_content": "full", "page_size": 50}
    again = await client.get("/admin/logs/config")
    assert again.json() == {"log_content": "full", "page_size": 50}


# ---------- upstreams ----------


async def test_list_upstreams_only_mock_seed(client: AsyncClient) -> None:
    """全新 DB 只含 migration seed 的 mock 上游。"""
    r = await client.get("/admin/upstreams")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["name"] == "mock"
    assert items[0]["provider"] == "mock"


async def test_create_upstream_success(client: AsyncClient) -> None:
    r = await client.post(
        "/admin/upstreams",
        json={
            "name": "ant-main",
            "native_api": "messages",
            "api_key": "sk-ant-xxx",
            "base_url": "https://api.example.com/ant-main",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "ant-main"
    assert body["native_api"] == "messages"
    assert body["enabled"] is True
    assert body["is_default"] is False  # 新建默认不是 default
    assert body["api_key"] == "sk-ant-xxx"
    assert "has_api_key" not in body


async def test_create_upstream_name_conflict(client: AsyncClient) -> None:
    payload = {
        "name": "dup",
        "native_api": "completions",
        "api_key": "sk-1",
        "base_url": "https://api.example.com/dup",
    }
    r1 = await client.post("/admin/upstreams", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/admin/upstreams", json=payload)
    assert r2.status_code == 409
    assert "已存在" in r2.json()["detail"]


async def test_create_upstream_unknown_type(client: AsyncClient) -> None:
    r = await client.post(
        "/admin/upstreams",
        json={
            "name": "c",
            "native_api": "unknown-server-api",
            "api_key": "sk",
            "base_url": "https://api.example.com/c",
        },
    )
    # Pydantic Literal 校验失败 → 422
    assert r.status_code == 422


async def test_create_upstream_rejects_any_native_api(client: AsyncClient) -> None:
    """`any` 是 mock 专用占位值,用户不可手动建。"""
    r = await client.post(
        "/admin/upstreams",
        json={
            "name": "c",
            "native_api": "any",
            "api_key": "sk",
            "base_url": "https://api.example.com/c",
        },
    )
    assert r.status_code == 422


async def test_list_upstreams_after_create(client: AsyncClient) -> None:
    await client.post(
        "/admin/upstreams",
        json={
            "name": "p1",
            "native_api": "messages",
            "api_key": "sk-1",
            "base_url": "https://api.example.com/p1",
        },
    )
    await client.post(
        "/admin/upstreams",
        json={
            "name": "p2",
            "native_api": "completions",
            "api_key": "sk-2",
            "base_url": "https://api.example.com/p2",
        },
    )
    r = await client.get("/admin/upstreams")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    # seed 的 mock 在最前(created_at 更早 / id 全零最小);p1/p2 顺序由随机 UUID
    # 的字典序决定,同秒 created_at 下两者可能翻转,只断言集合。
    assert names[0] == "mock"
    assert set(names[1:]) == {"p1", "p2"}


async def test_delete_upstream_success(client: AsyncClient, session: AsyncSession) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "doomed",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/doomed",
        },
    )
    pid = create.json()["id"]
    r = await client.delete(f"/admin/upstreams/{pid}")
    assert r.status_code == 204
    assert r.content == b""

    # DB 里确实没了
    result = await session.execute(select(Upstream).where(Upstream.id == pid))
    assert result.scalar_one_or_none() is None


async def test_delete_upstream_not_found(client: AsyncClient) -> None:
    r = await client.delete("/admin/upstreams/99999")
    assert r.status_code == 404


# ---------- restore-mock ----------


async def test_restore_mock_idempotent_when_exists(client: AsyncClient) -> None:
    """seed 已存在:restore-mock 返回 created=false,不重复插入。"""
    r = await client.post("/admin/upstreams/restore-mock")
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is False
    assert body["upstream"]["name"] == "mock"
    assert body["upstream"]["provider"] == "mock"

    # 第二次调用依然幂等
    r2 = await client.post("/admin/upstreams/restore-mock")
    assert r2.json()["created"] is False


async def test_restore_mock_recreates_after_delete(
    client: AsyncClient, session: AsyncSession
) -> None:
    """手动删掉 mock 后 restore-mock 应重建。"""
    lst = (await client.get("/admin/upstreams")).json()
    mock_id = next(u["id"] for u in lst if u["name"] == "mock")
    assert (await client.delete(f"/admin/upstreams/{mock_id}")).status_code == 204

    r = await client.post("/admin/upstreams/restore-mock")
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["upstream"]["id"] == mock_id  # id 固定,不随机

    # DB 里也对得上
    result = await session.execute(select(Upstream).where(Upstream.name == "mock"))
    assert result.scalar_one().provider == "mock"


async def test_restore_mock_force_rebuilds(client: AsyncClient) -> None:
    """?force=true 即使 mock 存在也先删后建,created=True。"""
    r = await client.post("/admin/upstreams/restore-mock?force=true")
    assert r.status_code == 200
    assert r.json()["created"] is True


# ---------- default ----------


async def test_set_default_success(client: AsyncClient) -> None:
    """PUT /admin/upstreams/{name}/default 设默认,is_default 翻 true。"""
    await client.post(
        "/admin/upstreams",
        json={
            "name": "p1",
            "native_api": "messages",
            "api_key": "sk-1",
            "base_url": "https://api.example.com/p1",
        },
    )
    r = await client.put("/admin/upstreams/p1/default")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "p1"
    assert body["is_default"] is True


async def test_set_default_switches_old_global_default(client: AsyncClient) -> None:
    """切 global default 时,旧 global default 的 is_default 归零。"""
    for name, native_api in (("a", "messages"), ("b", "completions")):
        await client.post(
            "/admin/upstreams",
            json={
                "name": name,
                "native_api": native_api,
                "api_key": "sk",
                "base_url": f"https://api.example.com/{name}",
            },
        )
    assert (await client.put("/admin/upstreams/a/default")).status_code == 200
    assert (await client.put("/admin/upstreams/b/default")).status_code == 200

    listed = (await client.get("/admin/upstreams")).json()
    a_row = next(u for u in listed if u["name"] == "a")
    b_row = next(u for u in listed if u["name"] == "b")
    assert a_row["is_default"] is False
    assert b_row["is_default"] is True


async def test_set_default_per_server_api(client: AsyncClient) -> None:
    """?server_api=xxx 设 per-server_api default,列表按对应 server_api 显示 default。"""
    for name, native_api in (("a", "messages"), ("b", "completions")):
        await client.post(
            "/admin/upstreams",
            json={
                "name": name,
                "native_api": native_api,
                "api_key": "sk",
                "base_url": f"https://api.example.com/{name}",
            },
        )
    assert (await client.put("/admin/upstreams/a/default?server_api=messages")).status_code == 200
    assert (
        await client.put("/admin/upstreams/b/default?server_api=completions")
    ).status_code == 200

    messages_list = (await client.get("/admin/upstreams?server_api=messages")).json()
    completions_list = (await client.get("/admin/upstreams?server_api=completions")).json()
    a_messages = next(u for u in messages_list if u["name"] == "a")
    b_messages = next(u for u in messages_list if u["name"] == "b")
    a_completions = next(u for u in completions_list if u["name"] == "a")
    b_completions = next(u for u in completions_list if u["name"] == "b")
    assert a_messages["is_default"] is True
    assert b_messages["is_default"] is False
    assert a_completions["is_default"] is False
    assert b_completions["is_default"] is True


async def test_get_upstream_defaults(client: AsyncClient) -> None:
    """专用 defaults 端点直接返回 global + per-server_api 绑定。"""
    await client.post(
        "/admin/upstreams",
        json={
            "name": "shared",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/shared",
        },
    )
    assert (await client.put("/admin/upstreams/shared/default")).status_code == 200
    assert (
        await client.put("/admin/upstreams/mock/default?server_api=responses")
    ).status_code == 200

    r = await client.get("/admin/upstreams/defaults")

    assert r.status_code == 200
    assert r.json() == {
        "global": "shared",
        "messages": None,
        "completions": None,
        "responses": "mock",
    }


async def test_test_upstream_success(client: AsyncClient) -> None:
    captured: dict[str, httpx.Request | None] = {"request": None}

    def _dispatch(req: httpx.Request) -> httpx.Response:
        captured["request"] = req
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_1",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "pong"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    prev = forwarder._client
    client_mock = httpx.AsyncClient(transport=httpx.MockTransport(_dispatch))
    forwarder._client = client_mock
    try:
        create = await client.post(
            "/admin/upstreams",
            json={
                "name": "oai",
                "native_api": "completions",
                "api_key": "sk",
                "model": "gpt-4o-mini",
                "base_url": "https://api.example.com/oai",
            },
        )
        upstream_id = create.json()["id"]

        r = await client.post(f"/admin/upstreams/{upstream_id}/test")

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["category"] == "ok"
        assert body["status_code"] == 200
        assert "api_key/model" in body["summary"]
        assert captured["request"] is not None
        assert captured["request"].url.path == "/oai/v1/chat/completions"
        assert captured["request"].headers["authorization"] == "Bearer sk"
    finally:
        await client_mock.aclose()
        forwarder._client = prev


async def test_test_upstream_missing_model_reports_config(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "oai-no-model",
            "native_api": "completions",
            "api_key": "sk",
            "base_url": "https://api.example.com/oai",
        },
    )
    upstream_id = create.json()["id"]

    r = await client.post(f"/admin/upstreams/{upstream_id}/test")

    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["category"] == "config"
    assert "缺少 model" in r.json()["summary"]


async def test_test_upstream_auth_failure_reports_auth(client: AsyncClient) -> None:
    def _dispatch(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    prev = forwarder._client
    client_mock = httpx.AsyncClient(transport=httpx.MockTransport(_dispatch))
    forwarder._client = client_mock
    try:
        create = await client.post(
            "/admin/upstreams",
            json={
                "name": "oai-auth",
                "native_api": "completions",
                "api_key": "sk-bad",
                "model": "gpt-4o-mini",
                "base_url": "https://api.example.com/oai",
            },
        )
        upstream_id = create.json()["id"]

        r = await client.post(f"/admin/upstreams/{upstream_id}/test")

        assert r.status_code == 200
        assert r.json()["ok"] is False
        assert r.json()["category"] == "auth"
        assert r.json()["status_code"] == 401
    finally:
        await client_mock.aclose()
        forwarder._client = prev


async def test_set_default_not_found(client: AsyncClient) -> None:
    r = await client.put("/admin/upstreams/ghost/default")
    assert r.status_code == 404


# ---------- update ----------


async def test_update_upstream_partial(client: AsyncClient) -> None:
    """PUT /admin/upstreams/{id} 部分字段;其他字段保持原值。"""
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "u1",
            "native_api": "messages",
            "api_key": "sk-1",
            "base_url": "https://api.example.com/u1",
        },
    )
    pid = create.json()["id"]
    r = await client.put(
        f"/admin/upstreams/{pid}",
        json={"base_url": "https://api.example.com/v2", "model": "claude-sonnet-4-5"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["base_url"] == "https://api.example.com/v2"
    assert body["model"] == "claude-sonnet-4-5"
    assert body["name"] == "u1"  # 未传字段不动


async def test_update_upstream_clear_api_key(client: AsyncClient) -> None:
    """传 api_key=null 清空。"""
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "u2",
            "native_api": "messages",
            "api_key": "sk-2",
            "base_url": "https://api.example.com/u2",
        },
    )
    pid = create.json()["id"]
    r = await client.put(f"/admin/upstreams/{pid}", json={"api_key": None})
    assert r.status_code == 200
    assert r.json()["api_key"] is None
    assert "has_api_key" not in r.json()


async def test_update_upstream_native_api_keeps_default(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "u3",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/u3",
        },
    )
    pid = create.json()["id"]
    assert (await client.put("/admin/upstreams/u3/default")).status_code == 200
    r = await client.put(f"/admin/upstreams/{pid}", json={"native_api": "completions"})
    assert r.status_code == 200
    body = r.json()
    assert body["native_api"] == "completions"
    assert body["is_default"] is True


async def test_update_upstream_not_found(client: AsyncClient) -> None:
    # mock seed 占了 "0"*32,用 "f"*32 一定不存在
    r = await client.put("/admin/upstreams/" + "f" * 32, json={"name": "x"})
    assert r.status_code == 404


async def test_update_upstream_name_conflict(client: AsyncClient) -> None:
    await client.post(
        "/admin/upstreams",
        json={
            "name": "taken",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/taken",
        },
    )
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "free",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/free",
        },
    )
    pid = create.json()["id"]
    r = await client.put(f"/admin/upstreams/{pid}", json={"name": "taken"})
    assert r.status_code == 409


async def test_update_upstream_empty_payload(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "u4",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/u4",
        },
    )
    pid = create.json()["id"]
    r = await client.put(f"/admin/upstreams/{pid}", json={})
    assert r.status_code == 400


# ---------- /admin/logs since polling 语义 ----------


async def test_logs_since_strictly_greater(client: AsyncClient, session: AsyncSession) -> None:
    """`?since=T` 只返 created_at > T 的记录(严格大于,为 polling 游标服务)。"""
    from datetime import UTC, datetime, timedelta

    from rosetta.server.database.models import LogEntry

    base = datetime.now(UTC).replace(microsecond=0)
    for i, delta in enumerate([0, 10, 20]):  # 三条,间隔 10s
        session.add(
            LogEntry(
                id=f"{i:0>32}",
                upstream_id=None,
                model=f"m-{i}",
                status="ok",
                latency_ms=i,
                created_at=base + timedelta(seconds=delta),
            )
        )
    await session.commit()

    # since = 第二条的时间 → 只应拿到第三条(严格大于)
    cutoff = (base + timedelta(seconds=10)).isoformat()
    r = await client.get("/admin/logs", params={"since": cutoff})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    items = body["items"]
    assert len(items) == 1
    assert items[0]["model"] == "m-2"


async def test_logs_total_independent_of_limit(client: AsyncClient, session: AsyncSession) -> None:
    """response.total 反映同条件下全表计数,不受 limit 影响(分页器靠它算 totalPages)。"""
    from datetime import UTC, datetime, timedelta

    from rosetta.server.database.models import LogEntry

    base = datetime.now(UTC).replace(microsecond=0)
    for i in range(7):
        session.add(
            LogEntry(
                id=f"{i:0>32}",
                upstream_id=None,
                model=f"m-{i}",
                status="ok",
                latency_ms=i,
                created_at=base + timedelta(seconds=i),
            )
        )
    await session.commit()

    r = await client.get("/admin/logs", params={"limit": 3, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 7  # 全表 7 条
    assert len(body["items"]) == 3  # 当前页 3 条
