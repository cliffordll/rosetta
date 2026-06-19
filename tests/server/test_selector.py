"""数据面 upstream 选择测试。

pick_upstream 两段策略(显式优先 + 全局 default fallback):
- header 有值 → 按 name 精确匹配(不存在 / 禁用 各自 400)
- header 缺失 → 找 enabled 的全局 default(没 default 400)
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository.upstream import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.service.selector import pick_upstream
from rosetta.shared.server_api import ServerApi


async def _insert_upstream(
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


class TestHeaderUpstream:
    async def test_header_exact_match(self, session: AsyncSession) -> None:
        u1 = await _insert_upstream(session, name="ant-a")
        _ = await _insert_upstream(session, name="ant-b")
        picked = await pick_upstream(
            session, header_upstream="ant-a", server_api=ServerApi.MESSAGES
        )
        assert picked.id == u1.id

    async def test_header_takes_precedence_over_default(self, session: AsyncSession) -> None:
        """header 显式指定时,即使有 global default,也以 header 为准。"""
        await _insert_upstream(session, name="dft")
        await UpstreamRepo(session).set_default("dft")
        u = await _insert_upstream(session, name="explicit")
        picked = await pick_upstream(
            session, header_upstream="explicit", server_api=ServerApi.MESSAGES
        )
        assert picked.id == u.id

    async def test_header_not_found_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="ghost", server_api=ServerApi.MESSAGES)
        assert exc.value.status == 400
        assert exc.value.code == "upstream_not_found"

    async def test_header_disabled_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a", enabled=False)
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="ant-a", server_api=ServerApi.MESSAGES)
        assert exc.value.status == 400
        assert exc.value.code == "upstream_disabled"


class TestDefaultFallback:
    async def test_no_header_uses_global_default(self, session: AsyncSession) -> None:
        u = await _insert_upstream(session, name="ant-a", native_api="messages")
        await UpstreamRepo(session).set_default("ant-a")
        picked = await pick_upstream(session, header_upstream=None, server_api=ServerApi.MESSAGES)
        assert picked.id == u.id

    async def test_empty_header_treated_as_missing(self, session: AsyncSession) -> None:
        u = await _insert_upstream(session, name="ant-a")
        await UpstreamRepo(session).set_default("ant-a")
        picked = await pick_upstream(session, header_upstream="", server_api=ServerApi.MESSAGES)
        assert picked.id == u.id

    async def test_no_header_no_default_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=None, server_api=ServerApi.MESSAGES)
        assert exc.value.status == 400
        assert exc.value.code == "missing_rosetta_upstream"

    async def test_default_disabled_falls_back_to_400(self, session: AsyncSession) -> None:
        """default 行被禁用 → 视为没 default,400(不静默兜底到其他行)。"""
        await _insert_upstream(session, name="ant-a", enabled=False)
        await UpstreamRepo(session).set_default("ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=None, server_api=ServerApi.MESSAGES)
        assert exc.value.status == 400
        assert exc.value.code == "missing_rosetta_upstream"

    async def test_global_default_crosses_api_types(self, session: AsyncSession) -> None:
        u = await _insert_upstream(session, name="ant-a", native_api="messages")
        await UpstreamRepo(session).set_default("ant-a")
        picked = await pick_upstream(
            session, header_upstream=None, server_api=ServerApi.CHAT_COMPLETIONS
        )
        assert picked.id == u.id
