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

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.controller import admin_router
from rosetta.server.database.models import Upstream
from rosetta.server.database.session import get_session


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
        json={"name": "ant-main", "protocol": "messages", "api_key": "sk-ant-xxx", "base_url": "https://api.example.com/ant-main"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "ant-main"
    assert body["protocol"] == "messages"
    assert body["enabled"] is True
    assert "api_key" not in body  # 不回显 api_key


async def test_create_upstream_name_conflict(client: AsyncClient) -> None:
    payload = {"name": "dup", "protocol": "completions", "api_key": "sk-1", "base_url": "https://api.example.com/dup"}
    r1 = await client.post("/admin/upstreams", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/admin/upstreams", json=payload)
    assert r2.status_code == 409
    assert "已存在" in r2.json()["detail"]


async def test_create_upstream_unknown_type(client: AsyncClient) -> None:
    r = await client.post(
        "/admin/upstreams",
        json={"name": "c", "protocol": "unknown-protocol", "api_key": "sk", "base_url": "https://api.example.com/c"},
    )
    # Pydantic Literal 校验失败 → 422
    assert r.status_code == 422


async def test_create_upstream_rejects_any_protocol(client: AsyncClient) -> None:
    """`any` 是 mock 专用占位值,用户不可手动建。"""
    r = await client.post(
        "/admin/upstreams",
        json={"name": "c", "protocol": "any", "api_key": "sk", "base_url": "https://api.example.com/c"},
    )
    assert r.status_code == 422


async def test_list_upstreams_after_create(client: AsyncClient) -> None:
    await client.post(
        "/admin/upstreams",
        json={"name": "p1", "protocol": "messages", "api_key": "sk-1", "base_url": "https://api.example.com/p1"},
    )
    await client.post(
        "/admin/upstreams",
        json={"name": "p2", "protocol": "completions", "api_key": "sk-2", "base_url": "https://api.example.com/p2"},
    )
    r = await client.get("/admin/upstreams")
    assert r.status_code == 200
    names = [p["name"] for p in r.json()]
    # seed 的 mock 在最前(created_at 更早 / id 全零最小);p1/p2 顺序由随机 UUID
    # 的字典序决定,同秒 created_at 下两者可能翻转,只断言集合。
    assert names[0] == "mock"
    assert set(names[1:]) == {"p1", "p2"}


async def test_delete_upstream_success(
    client: AsyncClient, session: AsyncSession
) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={"name": "doomed", "protocol": "messages", "api_key": "sk", "base_url": "https://api.example.com/doomed"},
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


# ---------- /admin/logs since polling 语义 ----------


async def test_logs_since_strictly_greater(
    client: AsyncClient, session: AsyncSession
) -> None:
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
    items = r.json()
    assert len(items) == 1
    assert items[0]["model"] == "m-2"
