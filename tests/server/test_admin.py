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
    assert body["upstreams_count"] == 0


# ---------- upstreams ----------


async def test_list_upstreams_empty(client: AsyncClient) -> None:
    r = await client.get("/admin/upstreams")
    assert r.status_code == 200
    assert r.json() == []


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
    assert names == ["p1", "p2"]  # 按 id ASC


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
