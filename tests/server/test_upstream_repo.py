"""UpstreamRepo 的 per-server_api + global default 行为。"""

from __future__ import annotations

import pytest
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


class TestGetDefault:
    async def test_no_default_returns_none(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        assert await UpstreamRepo(session).get_default("messages") is None

    async def test_per_server_api_default_hit(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api="messages")
        picked = await repo.get_default("messages")
        assert picked is not None
        assert picked.id == a.id

    async def test_global_default_fallback(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api=None)
        picked = await repo.get_default("completions")
        assert picked is not None
        assert picked.id == a.id

    async def test_per_server_api_takes_precedence_over_global(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        b = await _insert(session, name="b", native_api="completions")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api=None)
        await repo.set_default("b", server_api="completions")
        assert (await repo.get_default("messages")).id == a.id
        assert (await repo.get_default("completions")).id == b.id

    async def test_default_disabled_returns_none(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages", enabled=False)
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api="messages")
        assert await repo.get_default("messages") is None


class TestSetDefault:
    async def test_set_first_per_server_api_default(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.set_default("a", server_api="messages")
        assert await repo.default_upstream_id("messages") == result.id
        picked = await repo.get_default("messages")
        assert picked is not None and picked.name == "a"

    async def test_set_global_default(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.set_default("a", server_api=None)
        assert await repo.default_upstream_id("completions") == result.id

    async def test_switch_default_clears_old(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        await _insert(session, name="b", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api="messages")
        await repo.set_default("b", server_api="messages")
        picked = await repo.get_default("messages")
        assert picked is not None and picked.name == "b"
        assert await repo.default_upstream_id("messages") != a.id

    async def test_set_default_unknown_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            await repo.set_default("ghost", server_api="messages")

    async def test_set_default_idempotent(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api="messages")
        again = await repo.set_default("a", server_api="messages")
        assert await repo.default_upstream_id("messages") == again.id


class TestModelDefault:
    async def test_model_default_missing_returns_none(self, session: AsyncSession) -> None:
        assert await UpstreamRepo(session).default_model_upstream_id("gpt-4o") is None

    async def test_set_model_default(self, session: AsyncSession) -> None:
        upstream = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)

        result = await repo.set_model_default("a", "gpt-4o")

        assert result.id == upstream.id
        assert await repo.default_model_upstream_id("gpt-4o") == upstream.id
        assert await repo.list_model_defaults() == {"gpt-4o": "a"}

    async def test_set_model_default_unknown_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            await repo.set_model_default("ghost", "gpt-4o")


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
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await repo.update(b.id, name="a")

    async def test_update_native_api_keeps_default(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api="messages")
        result = await repo.update(a.id, native_api="completions")
        assert result.native_api == "completions"
        assert await repo.default_upstream_id("messages") == a.id

    async def test_update_native_api_unchanged_keeps_default(self, session: AsyncSession) -> None:
        """同 native_api(等值改)不影响 default。"""
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a", server_api="messages")
        await repo.update(a.id, native_api="messages")
        assert await repo.default_upstream_id("messages") == a.id

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
