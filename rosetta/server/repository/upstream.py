"""UpstreamRepo:upstreams 表的数据访问。

不抛 `HTTPException` —— 返回 None / 传递 `IntegrityError`,调用方决定 HTTP 语义。

`MOCK_UPSTREAM_FIELDS` 是内置 mock 上游的固定身份字段,`migrations/001_init.sql`
的 seed 和 `restore_mock` 都按它来,保证 id / name / provider 跨场景一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream

MOCK_UPSTREAM_FIELDS: dict[str, Any] = {
    "id": "0" * 32,
    "name": "mock",
    "protocol": "any",  # mock 不发 HTTP,protocol 字段语义不适用
    "provider": "mock",
    "base_url": "mock://",
    "api_key": None,
    "enabled": True,
}


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
        result = await self.session.execute(select(Upstream).where(Upstream.name == name))
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

    async def restore_mock(self, *, force: bool) -> tuple[bool, Upstream]:
        """恢复内置 mock 上游。幂等:存在则按 `force` 决定行为。

        - 不存在:按 `MOCK_UPSTREAM_FIELDS` 创建,返回 `(True, upstream)`
        - 存在 + `force=False`:不动,返回 `(False, 现有)`
        - 存在 + `force=True`:先 delete 再 insert,返回 `(True, 新建)`

        id 固定为 `MOCK_UPSTREAM_FIELDS["id"]`,`force` 重建时 logs.upstream_id
        的引用仍能对上;不会留死引用。
        """
        existing = await self.get_by_name(MOCK_UPSTREAM_FIELDS["name"])
        if existing is not None and not force:
            return (False, existing)
        if existing is not None:
            await self.delete(existing)

        fresh = Upstream(**MOCK_UPSTREAM_FIELDS)
        self.session.add(fresh)
        await self.session.commit()
        await self.session.refresh(fresh)
        return (True, fresh)
