"""数据面 provider 选择测试。

pick_provider 简化成"强制 header":客户端必须通过 `x-rosetta-provider` header
显式指定 provider。没 header / provider 不存在 / 被禁用都抛 `ServiceError(status=400, ...)`。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.service.selector import pick_provider


async def _insert_provider(
    session: AsyncSession, *, name: str, type_: str = "anthropic", enabled: bool = True
) -> Provider:
    p = Provider(name=name, type=type_, api_key="sk-fake", enabled=enabled)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


class TestHeaderProvider:
    async def test_header_exact_match(self, session: AsyncSession) -> None:
        p1 = await _insert_provider(session, name="ant-a")
        _ = await _insert_provider(session, name="ant-b")
        picked = await pick_provider(session, header_provider="ant-a")
        assert picked.id == p1.id

    async def test_header_missing_400(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_provider(session, header_provider=None)
        assert exc.value.status == 400
        assert exc.value.code == "missing_rosetta_provider"

    async def test_header_empty_400(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_provider(session, header_provider="")
        assert exc.value.status == 400
        assert exc.value.code == "missing_rosetta_provider"

    async def test_header_not_found_400(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant-a")
        with pytest.raises(ServiceError) as exc:
            await pick_provider(session, header_provider="ghost")
        assert exc.value.status == 400
        assert exc.value.code == "provider_not_found"

    async def test_header_disabled_400(self, session: AsyncSession) -> None:
        await _insert_provider(session, name="ant-a", enabled=False)
        with pytest.raises(ServiceError) as exc:
            await pick_provider(session, header_provider="ant-a")
        assert exc.value.status == 400
        assert exc.value.code == "provider_disabled"
