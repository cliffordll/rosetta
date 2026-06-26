"""UpstreamRepo 的 upstream 管理行为。"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository.upstream import UpstreamRepo


async def _insert(
    session: AsyncSession,
    *,
    name: str,
    native_api: str = "messages",
    enabled: bool = True,
) -> Upstream:
    u = Upstream(
        name=name,
        native_api=native_api,
        provider="custom",
        base_url="https://example.com",
        api_key="sk-fake",
        enabled=enabled,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


class TestModelTables:
    async def test_set_model_default(self, session: AsyncSession) -> None:
        upstream = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)

        model_id = await repo.get_or_create_model("gpt-4o")
        await repo.set_upstream_model(upstream.id, model_id, is_default=True)

        assert await repo.list_model_defaults() == {"gpt-4o": upstream.id}

    async def test_set_model_alias_and_enabled(self, session: AsyncSession) -> None:
        upstream = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        model_id = await repo.get_or_create_model("gpt-4o")
        await repo.set_upstream_model(upstream.id, model_id, is_default=True)

        await repo.set_model_alias("gpt-4o", "gpt-5-codex")
        await repo.set_model_enabled("gpt-4o", False)

        models = [m for m in await repo.list_models() if m["name"] == "gpt-4o"]
        assert models == [
            {
                "id": model_id,
                "name": "gpt-4o",
                "alias": "gpt-5-codex",
                "enabled": False,
                "upstreams": "a",
                "has_default": True,
            }
        ]

    async def test_delete_upstream_clears_matching_model_default(
        self, session: AsyncSession
    ) -> None:
        upstream = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        model_id = await repo.get_or_create_model("gpt-4o")
        await repo.set_upstream_model(upstream.id, model_id, is_default=True)

        await repo.delete(upstream)

        assert await repo.list_model_defaults() == {}
        assert all(m["name"] != "gpt-4o" for m in await repo.list_models())

    async def test_delete_one_upstream_keeps_shared_model(self, session: AsyncSession) -> None:
        first = await _insert(session, name="a", native_api="messages")
        second = await _insert(session, name="b", native_api="messages")
        repo = UpstreamRepo(session)
        model_id = await repo.get_or_create_model("gpt-4o")
        await repo.set_upstream_model(first.id, model_id, is_default=False)
        await repo.set_upstream_model(second.id, model_id, is_default=True)

        await repo.delete(first)

        assert await repo.list_model_defaults() == {"gpt-4o": second.id}
        models = [m for m in await repo.list_models() if m["name"] == "gpt-4o"]
        assert len(models) == 1
        assert models[0]["name"] == "gpt-4o"
        assert models[0]["upstreams"] == "b"


class TestUpdate:
    async def test_update_single_field(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, base_url="https://new.example.com")
        assert result.base_url == "https://new.example.com"
        assert result.name == "a"  # 其他字段不动

    async def test_update_unknown_id_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            # mock seed 占了 "0"*32,用 "f"*32 一定不存在
            await repo.update("f" * 32, name="ghost")

    async def test_update_name_conflict(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        b = await _insert(session, name="b", native_api="messages")
        repo = UpstreamRepo(session)

        with pytest.raises(IntegrityError):
            await repo.update(b.id, name="a")

    async def test_update_native_api(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, native_api="completions")
        assert result.native_api == "completions"

    async def test_update_clear_api_key(self, session: AsyncSession) -> None:
        """显式传 None 清 api_key;不传字段保持原值。"""
        a = await _insert(session, name="a")
        assert a.api_key == "sk-fake"
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, api_key=None)
        assert result.api_key is None

    async def test_update_omit_api_key_keeps_original(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, base_url="https://x")
        assert result.api_key == "sk-fake"

    async def test_update_set_model(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a")
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, model="claude-sonnet-4-5")
        assert result.model == "claude-sonnet-4-5"
