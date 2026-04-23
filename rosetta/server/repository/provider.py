"""ProviderRepo:provider 表的数据访问。

不抛 `HTTPException` —— 返回 None / 传递 `IntegrityError`,调用方决定 HTTP 语义。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider


class ProviderRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[Provider]:
        result = await self.session.execute(select(Provider).order_by(Provider.id))
        return result.scalars().all()

    async def get_by_id(self, provider_id: int) -> Provider | None:
        return await self.session.get(Provider, provider_id)

    async def get_by_name(self, name: str) -> Provider | None:
        result = await self.session.execute(
            select(Provider).where(Provider.name == name)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Provider))
        return int(result.scalar_one())

    async def create(
        self,
        *,
        name: str,
        type_: str,
        base_url: str | None,
        api_key: str,
        enabled: bool,
    ) -> Provider:
        """创建 provider;name 冲突时 rollback 并抛 `IntegrityError`(调用方转 409)。"""
        provider = Provider(
            name=name,
            type=type_,
            base_url=base_url,
            api_key=api_key,
            enabled=enabled,
        )
        self.session.add(provider)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise
        await self.session.refresh(provider)
        return provider

    async def delete(self, provider: Provider) -> None:
        await self.session.delete(provider)
        await self.session.commit()
