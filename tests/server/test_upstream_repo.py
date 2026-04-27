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
