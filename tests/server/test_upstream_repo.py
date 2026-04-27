"""UpstreamRepo 的 get_default / set_default 行为。

partial unique index `(protocol) WHERE is_default=1` 由 DB 兜底唯一,
set_default 在事务内"先清同 protocol 旧 default、再 set 目标"。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository.upstream import UpstreamRepo


async def _insert(
    session: AsyncSession,
    *,
    name: str,
    protocol: str = "messages",
    enabled: bool = True,
    is_default: bool = False,
) -> Upstream:
    u = Upstream(
        name=name,
        protocol=protocol,
        provider="custom",
        base_url="https://example.com",
        api_key="sk-fake",
        enabled=enabled,
        is_default=is_default,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


class TestGetDefault:
    async def test_no_default_returns_none(self, session: AsyncSession) -> None:
        await _insert(session, name="a", protocol="messages")
        assert await UpstreamRepo(session).get_default("messages") is None

    async def test_default_hit(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", protocol="messages", is_default=True)
        picked = await UpstreamRepo(session).get_default("messages")
        assert picked is not None
        assert picked.id == a.id

    async def test_default_disabled_returns_none(self, session: AsyncSession) -> None:
        await _insert(session, name="a", protocol="messages", enabled=False, is_default=True)
        assert await UpstreamRepo(session).get_default("messages") is None

    async def test_default_isolated_per_protocol(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", protocol="messages", is_default=True)
        b = await _insert(session, name="b", protocol="completions", is_default=True)
        repo = UpstreamRepo(session)
        m = await repo.get_default("messages")
        c = await repo.get_default("completions")
        assert m is not None and m.id == a.id
        assert c is not None and c.id == b.id


class TestSetDefault:
    async def test_set_first_default(self, session: AsyncSession) -> None:
        await _insert(session, name="a", protocol="messages")
        repo = UpstreamRepo(session)
        result = await repo.set_default("a")
        assert result.is_default is True
        picked = await repo.get_default("messages")
        assert picked is not None and picked.name == "a"

    async def test_switch_default_clears_old(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", protocol="messages", is_default=True)
        await _insert(session, name="b", protocol="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("b")
        # a 应被清零,b 现在是 default
        picked = await repo.get_default("messages")
        assert picked is not None and picked.name == "b"
        await session.refresh(a)
        assert a.is_default is False

    async def test_set_default_does_not_touch_other_protocols(self, session: AsyncSession) -> None:
        c = await _insert(session, name="c", protocol="completions", is_default=True)
        await _insert(session, name="a", protocol="messages")
        repo = UpstreamRepo(session)
        await repo.set_default("a")
        await session.refresh(c)
        assert c.is_default is True

    async def test_set_default_unknown_raises(self, session: AsyncSession) -> None:
        repo = UpstreamRepo(session)
        with pytest.raises(LookupError):
            await repo.set_default("ghost")

    async def test_set_default_idempotent(self, session: AsyncSession) -> None:
        await _insert(session, name="a", protocol="messages", is_default=True)
        repo = UpstreamRepo(session)
        again = await repo.set_default("a")
        assert again.is_default is True


class TestUpdate:
    async def test_update_single_field(self, session: AsyncSession) -> None:
        a = await _insert(session, name="a", protocol="messages")
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
        await _insert(session, name="a", protocol="messages")
        b = await _insert(session, name="b", protocol="messages")
        repo = UpstreamRepo(session)
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError):
            await repo.update(b.id, name="a")

    async def test_update_protocol_clears_is_default(self, session: AsyncSession) -> None:
        """改 protocol 时,如果该行原来是 default,应自动清掉(避免跨协议占槽)。"""
        a = await _insert(session, name="a", protocol="messages", is_default=True)
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, protocol="completions")
        assert result.protocol == "completions"
        assert result.is_default is False

    async def test_update_protocol_unchanged_keeps_is_default(self, session: AsyncSession) -> None:
        """同 protocol(等值改)不应清 is_default。"""
        a = await _insert(session, name="a", protocol="messages", is_default=True)
        repo = UpstreamRepo(session)
        result = await repo.update(a.id, protocol="messages")
        assert result.is_default is True

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
