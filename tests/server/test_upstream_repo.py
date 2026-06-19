"""UpstreamRepo 的全局 get_default / set_default 行为。"""

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
        assert await UpstreamRepo(session).get_default() is None

    async def test_default_hit(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        picked = await repo.get_default()
        assert picked is not None
        assert picked.id == a.id

    async def test_default_disabled_returns_none(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages", enabled=False)
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        assert await repo.get_default() is None


class TestSetDefault:
    async def test_set_first_default(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        result = await repo.set_default("a")
        assert await repo.default_upstream_id() == result.id
        picked = await repo.get_default()
        assert picked is not None and picked.name == "a"

    async def test_switch_default_clears_old(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        await _insert(session, name="b", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        await repo.set_default("b")
        picked = await repo.get_default()
        assert picked is not None and picked.name == "b"
        assert await repo.default_upstream_id() != a.id

    async def test_set_default_clears_other_native_api(self, session: AsyncSession) -> None:
        await _insert(session, name="c", native_api="completions")
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("c")
        await repo.set_default("a")
        assert await repo.default_upstream_id() == a.id

    async def test_set_default_unknown_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            await repo.set_default("ghost")

    async def test_set_default_idempotent(self, session: AsyncSession) -> None:
        await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        again = await repo.set_default("a")
        assert await repo.default_upstream_id() == again.id


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

    async def test_update_native_api_keeps_global_default(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        result = await repo.update(a.id, native_api="completions")
        assert result.native_api == "completions"
        assert await repo.default_upstream_id() == a.id

    async def test_update_native_api_unchanged_keeps_default(self, session: AsyncSession) -> None:
        """同 native_api(等值改)不影响 global default。"""
        a = await _insert(session, name="a", native_api="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        await repo.update(a.id, native_api="messages")
        assert await repo.default_upstream_id() == a.id

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
