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
from pathlib import Path

import httpx
import pytest
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


async def test_client_guide_returns_packaged_doc(client: AsyncClient) -> None:
    r = await client.get("/admin/upstreams/guide/opencode")
    assert r.status_code == 200
    body = r.json()
    assert body["client"] == "opencode"
    assert "OpenCode" in body["content"]


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
            "model": "test-model",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "ant-main"
    assert body["native_api"] == "messages"
    assert body["enabled"] is True
    assert body["api_key"] == "sk-ant-xxx"
    assert "has_api_key" not in body


async def test_create_upstream_requires_model(client: AsyncClient) -> None:
    r = await client.post(
        "/admin/upstreams",
        json={
            "name": "missing-model",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/missing-model",
        },
    )

    assert r.status_code == 422


async def test_update_upstream_rejects_empty_model(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "model-required",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/model-required",
            "model": "gpt-4o",
        },
    )
    pid = create.json()["id"]

    null_model = await client.put(f"/admin/upstreams/{pid}", json={"model": None})
    blank_model = await client.put(f"/admin/upstreams/{pid}", json={"model": "   "})

    assert null_model.status_code == 400
    assert blank_model.status_code == 422


async def test_create_upstream_name_conflict(client: AsyncClient) -> None:
    payload = {
        "name": "dup",
        "native_api": "completions",
        "api_key": "sk-1",
        "base_url": "https://api.example.com/dup",
        "model": "test-model",
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
            "model": "test-model",
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
            "model": "test-model",
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
            "model": "test-model",
        },
    )
    await client.post(
        "/admin/upstreams",
        json={
            "name": "p2",
            "native_api": "completions",
            "api_key": "sk-2",
            "base_url": "https://api.example.com/p2",
            "model": "test-model",
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
            "model": "test-model",
        },
    )
    pid = create.json()["id"]
    r = await client.delete(f"/admin/upstreams/{pid}")
    assert r.status_code == 204
    assert r.content == b""

    # DB 里确实没了
    result = await session.execute(select(Upstream).where(Upstream.id == pid))
    assert result.scalar_one_or_none() is None


async def test_delete_upstream_removes_model_default(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "defaulted",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/defaulted",
            "model": "test-model",
        },
    )
    pid = create.json()["id"]
    assert (
        await client.put(f"/admin/upstreams/{pid}/model-default?model=gpt-4o")
    ).status_code == 200

    r = await client.delete(f"/admin/upstreams/{pid}")

    assert r.status_code == 204
    defaults = await client.get("/admin/upstreams/model-defaults")
    assert defaults.json() == {}


async def test_delete_upstream_removes_orphan_model(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "single-model-owner",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/single-model-owner",
            "model": "unique-model",
        },
    )
    upstream_id = create.json()["id"]
    models_before = (await client.get("/admin/models")).json()
    assert any(item["name"] == "unique-model" for item in models_before)

    r = await client.delete(f"/admin/upstreams/{upstream_id}")

    assert r.status_code == 204
    models_after = (await client.get("/admin/models")).json()
    assert all(item["name"] != "unique-model" for item in models_after)


async def test_delete_one_upstream_keeps_shared_model(client: AsyncClient) -> None:
    first = await client.post(
        "/admin/upstreams",
        json={
            "name": "shared-a",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/shared-a",
            "model": "shared-model",
        },
    )
    await client.post(
        "/admin/upstreams",
        json={
            "name": "shared-b",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/shared-b",
            "model": "shared-model",
        },
    )

    r = await client.delete(f"/admin/upstreams/{first.json()['id']}")

    assert r.status_code == 204
    models = (await client.get("/admin/models")).json()
    assert any(item["name"] == "shared-model" for item in models)


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


# ---------- model default ----------


async def test_set_model_default_success(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "model-owner",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/model-owner",
            "model": "gpt-4o",
        },
    )
    upstream_id = create.json()["id"]

    r = await client.put(f"/admin/upstreams/{upstream_id}/model-default?model=gpt-4o")

    assert r.status_code == 200
    assert r.json()["name"] == "model-owner"


async def test_get_model_defaults(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "model-owner",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/model-owner",
            "model": "gpt-4o",
        },
    )
    upstream_id = create.json()["id"]
    assert (
        await client.put(f"/admin/upstreams/{upstream_id}/model-default?model=gpt-4o")
    ).status_code == 200

    r = await client.get("/admin/upstreams/model-defaults")

    assert r.status_code == 200
    assert r.json() == {"gpt-4o": upstream_id}


async def test_set_model_default_not_found(client: AsyncClient) -> None:
    r = await client.put("/admin/upstreams/ghost/model-default?model=gpt-4o")

    assert r.status_code == 404


async def test_model_alias_admin_endpoints(client: AsyncClient) -> None:
    await client.post(
        "/admin/upstreams",
        json={
            "name": "alias-owner",
            "native_api": "responses",
            "provider": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-v4-flash",
        },
    )

    updated = await client.put(
        "/admin/models/deepseek-v4-flash/alias",
        json={"alias": "gpt-5-codex"},
    )

    assert updated.status_code == 200
    assert updated.json()["alias"] == "gpt-5-codex"
    listed = await client.get("/admin/models")
    assert any(
        item["name"] == "deepseek-v4-flash" and item["alias"] == "gpt-5-codex"
        for item in listed.json()
    )

    cleared = await client.put(
        "/admin/models/deepseek-v4-flash/alias",
        json={"alias": None},
    )

    assert cleared.status_code == 200
    assert cleared.json()["alias"] is None


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
            "model": "test-model",
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
            "model": "test-model",
        },
    )
    pid = create.json()["id"]
    r = await client.put(f"/admin/upstreams/{pid}", json={"api_key": None})
    assert r.status_code == 200
    assert r.json()["api_key"] is None
    assert "has_api_key" not in r.json()


async def test_update_upstream_native_api(client: AsyncClient) -> None:
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "u3",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/u3",
            "model": "test-model",
        },
    )
    pid = create.json()["id"]
    r = await client.put(f"/admin/upstreams/{pid}", json={"native_api": "completions"})
    assert r.status_code == 200
    body = r.json()
    assert body["native_api"] == "completions"


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
            "model": "test-model",
        },
    )
    create = await client.post(
        "/admin/upstreams",
        json={
            "name": "free",
            "native_api": "messages",
            "api_key": "sk",
            "base_url": "https://api.example.com/free",
            "model": "test-model",
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
            "model": "test-model",
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


async def test_clear_logs_deletes_entries(client: AsyncClient, session: AsyncSession) -> None:
    from datetime import UTC, datetime

    from rosetta.server.database.models import LogEntry

    session.add_all(
        [
            LogEntry(
                id="1".zfill(32),
                upstream_id=None,
                model="m-1",
                status="ok",
                created_at=datetime.now(UTC),
            ),
            LogEntry(
                id="2".zfill(32),
                upstream_id=None,
                model="m-2",
                status="error",
                created_at=datetime.now(UTC),
            ),
        ]
    )
    await session.commit()

    r = await client.delete("/admin/logs")
    assert r.status_code == 200
    assert r.json() == {"deleted": 2}

    after = await client.get("/admin/logs")
    assert after.json()["total"] == 0
    assert after.json()["items"] == []


# ---------- chat config ----------


async def test_chat_config_defaults(client: AsyncClient) -> None:
    r = await client.get("/admin/chat/config")
    assert r.status_code == 200
    assert r.json() == {"max_tokens": 8192, "stream": True}


async def test_chat_config_update_max_tokens(client: AsyncClient) -> None:
    r = await client.put("/admin/chat/config", json={"max_tokens": 4096})
    assert r.status_code == 200
    assert r.json() == {"max_tokens": 4096, "stream": True}

    again = await client.get("/admin/chat/config")
    assert again.json() == {"max_tokens": 4096, "stream": True}


async def test_chat_config_update_stream(client: AsyncClient) -> None:
    r = await client.put("/admin/chat/config", json={"stream": False})
    assert r.status_code == 200
    assert r.json() == {"max_tokens": 8192, "stream": False}

    again = await client.get("/admin/chat/config")
    assert again.json() == {"max_tokens": 8192, "stream": False}


async def test_chat_config_update_both(client: AsyncClient) -> None:
    r = await client.put("/admin/chat/config", json={"max_tokens": 4096, "stream": False})
    assert r.status_code == 200
    assert r.json() == {"max_tokens": 4096, "stream": False}

    again = await client.get("/admin/chat/config")
    assert again.json() == {"max_tokens": 4096, "stream": False}


async def test_chat_config_empty_update_noop(client: AsyncClient) -> None:
    r = await client.put("/admin/chat/config", json={})
    assert r.status_code == 200
    assert r.json() == {"max_tokens": 8192, "stream": True}


async def test_setup_preview_returns_original_and_generated_config(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROSETTA_SETUP_CONFIG_HOME", str(tmp_path))
    existing = tmp_path / ".codex" / "config.toml"
    existing.parent.mkdir(parents=True)
    existing.write_text('model = "old"\n', encoding="utf-8")
    await client.post(
        "/admin/upstreams",
        json={
            "name": "ds",
            "native_api": "responses",
            "provider": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-v4-flash",
        },
    )

    r = await client.get(
        "/admin/setup/codex/preview",
        params={"model": "deepseek-v4-flash"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "codex"
    assert body["path"].endswith((".codex/config.toml", ".codex\\config.toml"))
    assert body["exists"] is True
    assert body["original"] == 'model = "old"\n'
    assert 'model = "deepseek-v4-flash"' in body["generated"]
    assert body["backup_path"] is None


async def test_setup_apply_backs_up_and_writes_config(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROSETTA_SETUP_CONFIG_HOME", str(tmp_path))
    existing = tmp_path / ".claude" / "settings.json"
    existing.parent.mkdir(parents=True)
    existing.write_text('{"old": true}\n', encoding="utf-8")
    await client.post(
        "/admin/upstreams",
        json={
            "name": "ds",
            "native_api": "messages",
            "provider": "anthropic",
            "base_url": "https://api.example.com",
            "model": "deepseek-v4-flash",
        },
    )

    r = await client.post(
        "/admin/setup/claude/apply",
        json={"model": "deepseek-v4-flash"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "claude"
    assert body["backup_path"] is not None
    assert Path(body["backup_path"]).read_text(encoding="utf-8") == '{"old": true}\n'
    assert existing.read_text(encoding="utf-8") == body["generated"]
    assert '"ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-flash"' in body["generated"]


async def test_setup_apply_uses_model_alias(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROSETTA_SETUP_CONFIG_HOME", str(tmp_path))
    await client.post(
        "/admin/upstreams",
        json={
            "name": "ds",
            "native_api": "responses",
            "provider": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    alias = await client.put(
        "/admin/models/deepseek-v4-flash/alias",
        json={"alias": "gpt-5-codex"},
    )
    assert alias.status_code == 200

    r = await client.post(
        "/admin/setup/codex/apply",
        json={"model": "deepseek-v4-flash"},
    )

    assert r.status_code == 200
    assert r.json()["alias"] == "gpt-5-codex"
    assert 'model = "gpt-5-codex"' in r.json()["generated"]


async def test_setup_current_returns_model_alias_from_config(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROSETTA_SETUP_CONFIG_HOME", str(tmp_path))
    await client.post(
        "/admin/upstreams",
        json={
            "name": "codex-owner",
            "native_api": "responses",
            "provider": "openai",
            "base_url": "https://api.example.com/v1",
            "model": "deepseek-v4-flash",
        },
    )
    await client.post(
        "/admin/upstreams",
        json={
            "name": "claude-owner",
            "native_api": "messages",
            "provider": "anthropic",
            "base_url": "https://api.example.com",
            "model": "claude-sonnet-4-5",
        },
    )
    assert (
        await client.put(
            "/admin/models/deepseek-v4-flash/alias",
            json={"alias": "gpt-5-codex"},
        )
    ).status_code == 200
    assert (
        await client.put(
            "/admin/models/claude-sonnet-4-5/alias",
            json={"alias": "claude-sonnet-alias"},
        )
    ).status_code == 200

    codex_config = tmp_path / ".codex" / "config.toml"
    codex_config.parent.mkdir(parents=True)
    codex_config.write_text('model = "gpt-5-codex"\n', encoding="utf-8")
    claude_config = tmp_path / ".claude" / "settings.json"
    claude_config.parent.mkdir(parents=True)
    claude_config.write_text(
        '{"env": {"ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-alias"}}\n',
        encoding="utf-8",
    )

    codex = await client.get("/admin/setup/codex/current")
    claude = await client.get("/admin/setup/claude/current")
    opencode = await client.get("/admin/setup/opencode/current")

    assert codex.status_code == 200
    assert codex.json()["model"] == "deepseek-v4-flash"
    assert codex.json()["alias"] == "gpt-5-codex"
    assert 'model = "gpt-5-codex"' in codex.json()["generated"]
    assert claude.status_code == 200
    assert claude.json()["model"] == "claude-sonnet-4-5"
    assert claude.json()["alias"] == "claude-sonnet-alias"
    assert "claude-sonnet-alias" in claude.json()["generated"]
    assert opencode.status_code == 200
    assert opencode.json()["model"] is None
    assert opencode.json()["alias"] is None


async def test_setup_preview_unknown_model_returns_404(client: AsyncClient) -> None:
    r = await client.get("/admin/setup/codex/preview", params={"model": "missing"})

    assert r.status_code == 404


async def test_setup_clear_preview_removes_rosetta_config(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROSETTA_SETUP_CONFIG_HOME", str(tmp_path))
    existing = tmp_path / ".codex" / "config.toml"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "# keep\n"
        'model = "deepseek"\n'
        'custom_setting = "keep"\n'
        "\n"
        "[model_providers.rosetta]\n"
        'base_url = "http://localhost:1687"\n',
        encoding="utf-8",
    )

    r = await client.get("/admin/setup/codex/clear-preview")

    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "codex"
    assert body["exists"] is True
    assert "# keep" in body["generated"]
    assert 'custom_setting = "keep"' in body["generated"]
    assert 'model = "deepseek"' not in body["generated"]
    assert "[model_providers.rosetta]" not in body["generated"]


async def test_setup_clear_backs_up_and_writes_config(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROSETTA_SETUP_CONFIG_HOME", str(tmp_path))
    existing = tmp_path / ".claude" / "settings.json"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        '{"env": {"ANTHROPIC_BASE_URL": "http://localhost:1687", "MY_VAR": "keep"}}\n',
        encoding="utf-8",
    )

    r = await client.post("/admin/setup/claude/clear")

    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "claude"
    assert body["backup_path"] is not None
    assert Path(body["backup_path"]).read_text(encoding="utf-8").startswith('{"env"')
    assert existing.read_text(encoding="utf-8") == body["generated"]
    assert "ANTHROPIC_BASE_URL" not in body["generated"]
    assert "MY_VAR" in body["generated"]
