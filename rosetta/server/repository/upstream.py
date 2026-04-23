"""UpstreamRepo:upstreams 表的数据访问。

不抛 `HTTPException` —— 返回 None / 传递 `IntegrityError`,调用方决定 HTTP 语义。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream


class UpstreamRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[Upstream]:
        result = await self.session.execute(
            select(Upstream).order_by(Upstream.created_at, Upstream.id)
        )
        return result.scalars().all()

    async def get_by_id(self, upstream_id: str) -> Upstream | None:
        return await self.session.get(Upstream, upstream_id)

    async def get_by_name(self, name: str) -> Upstream | None:
        result = await self.session.execute(
            select(Upstream).where(Upstream.name == name)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Upstream))
        return int(result.scalar_one())

    async def create(
        self,
        *,
        name: str,
        protocol: str,
        provider: str,
        base_url: str,
        api_key: str | None,
        enabled: bool,
    ) -> Upstream:
        """创建 upstream;name 冲突时 rollback 并抛 `IntegrityError`(调用方转 409)。"""
        upstream = Upstream(
            name=name,
            protocol=protocol,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            enabled=enabled,
        )
        self.session.add(upstream)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise
        await self.session.refresh(upstream)
        return upstream

    async def delete(self, upstream: Upstream) -> None:
        await self.session.delete(upstream)
        await self.session.commit()
