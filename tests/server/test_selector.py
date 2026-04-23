"""数据面 upstream 选择测试。

pick_upstream 简化成"强制 header":客户端必须通过 `x-rosetta-upstream` header
显式指定 upstream。没 header / upstream 不存在 / 被禁用都抛 `ServiceError(status=400, ...)`。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.service.selector import pick_upstream


async def _insert_upstream(
    session: AsyncSession, *, name: str, protocol: str = "messages", enabled: bool = True
) -> Upstream:
    u = Upstream(
        name=name,
        protocol=protocol,
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
        picked = await pick_upstream(session, header_upstream="ant-a")
        assert picked.id == u1.id

    async def test_header_missing_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream=None)
        assert exc.value.status == 400
        assert exc.value.code == "missing_rosetta_upstream"

    async def test_header_empty_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="")
        assert exc.value.status == 400
        assert exc.value.code == "missing_rosetta_upstream"

    async def test_header_not_found_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="ghost")
        assert exc.value.status == 400
        assert exc.value.code == "upstream_not_found"

    async def test_header_disabled_400(self, session: AsyncSession) -> None:
        await _insert_upstream(session, name="ant-a", enabled=False)
        with pytest.raises(ServiceError) as exc:
            await pick_upstream(session, header_upstream="ant-a")
        assert exc.value.status == 400
        assert exc.value.code == "upstream_disabled"
