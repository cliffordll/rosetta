"""UpstreamRepo:upstreams 表的数据访问。

不抛 `HTTPException` —— 返回 None / 传递 `IntegrityError`,调用方决定 HTTP 语义。

`MOCK_UPSTREAM_FIELDS` 是内置 mock 上游的固定身份字段,`migrations/001_init.sql`
的 seed 和 `restore_mock` 都按它来,保证 id / name / provider 跨场景一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from types import EllipsisType
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import ApiType, Upstream

MOCK_UPSTREAM_FIELDS: dict[str, Any] = {
    "id": "0" * 32,
    "name": "mock",
    "native_api": "any",  # mock 不发 HTTP,native_api 字段语义不适用
    "provider": "mock",
    "base_url": "mock://",
    "api_key": None,
    "model": None,  # mock 路径不走 forwarder model fallback;client 自带
    "enabled": True,
    "is_default": False,  # mock 不参与默认 upstream 路由
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

    async def api_type_paths(self) -> dict[str, str]:
        """读取启用的 API 类型 name → path 映射,供 forwarder 拼上游 URL。"""
        result = await self.session.execute(
            select(ApiType).where(ApiType.enabled.is_(True)).order_by(ApiType.name)
        )
        return {api_type.name: api_type.path for api_type in result.scalars().all()}

    async def create(
        self,
        *,
        name: str,
        native_api: str,
        provider: str,
        base_url: str,
        api_key: str | None,
        model: str | None,
        enabled: bool,
    ) -> Upstream:
        """创建 upstream;name 冲突时 rollback 并抛 `IntegrityError`(调用方转 409)。"""
        upstream = Upstream(
            name=name,
            native_api=native_api,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
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

    async def update(
        self,
        upstream_id: str,
        *,
        name: str | None = None,
        native_api: str | None = None,
        provider: str | None = None,
        base_url: str | None = None,
        api_key: str | None | EllipsisType = ...,
        model: str | None | EllipsisType = ...,
        enabled: bool | None = None,
    ) -> Upstream:
        """部分更新 upstream;只改传入的字段。

        - id 不存在 → `LookupError`(调用方转 404)
        - name 冲突 → `IntegrityError`(调用方转 409)
        - native_api 改了且原行 `is_default=True` → 自动清掉 is_default(原 native_api
          的 default 槽位空缺),避免"messages 的 default 突然变成 completions 的"
          这种隐式语义跳变;调用方应在 UI 提示用户重新 set-default
        - api_key / model 用 sentinel `...`(Ellipsis) 区分"传 None 显式清空"和
          "未传保持原值";其他字段用 None 即"未传"
        """
        target = await self.get_by_id(upstream_id)
        if target is None:
            raise LookupError(f"upstream id={upstream_id!r} 不存在")

        if name is not None:
            target.name = name
        if provider is not None:
            target.provider = provider
        if base_url is not None:
            target.base_url = base_url
        if api_key is not ...:
            target.api_key = api_key
        if model is not ...:
            target.model = model
        if enabled is not None:
            target.enabled = enabled
        if native_api is not None and native_api != target.native_api:
            target.native_api = native_api
            # 旧 native_api 的 default 槽位被该行占用过的话,改 native_api 后清掉
            target.is_default = False

        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise
        await self.session.refresh(target)
        return target

    async def delete(self, upstream: Upstream) -> None:
        await self.session.delete(upstream)
        await self.session.commit()

    async def get_default(self, native_api: str) -> Upstream | None:
        """按 native_api 查 enabled 的 default upstream(没设 / 被禁 / 不存在 → None)。

        DB 层有 partial unique index `(native_api) WHERE is_default=1` 兜底唯一,
        所以这里 `scalar_one_or_none()` 安全;命中行若 enabled=False,视为没 default。
        """
        result = await self.session.execute(
            select(Upstream).where(
                Upstream.native_api == native_api,
                Upstream.is_default.is_(True),
                Upstream.enabled.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def set_default(self, name: str) -> Upstream:
        """把 `name` 设为其 native_api 的 default;同 native_api 的旧 default 自动清零。

        两步发 SQL(同事务):
          1. UPDATE upstreams SET is_default=0 WHERE native_api=<target> AND id != <target.id>
          2. UPDATE upstreams SET is_default=1 WHERE id = <target.id>
        SQLite 默认 immediate 约束,partial unique index 在每条 statement 后检查,
        先清零再 set 不会瞬时冲突。

        - name 不存在 → `LookupError`(调用方转 404)
        - mock 行(native_api='any')也允许设,但 selector 不会查 'any';无副作用
        """
        target = await self.get_by_name(name)
        if target is None:
            raise LookupError(f"upstream name={name!r} 不存在")

        await self.session.execute(
            update(Upstream)
            .where(Upstream.native_api == target.native_api, Upstream.id != target.id)
            .values(is_default=False)
        )
        await self.session.execute(
            update(Upstream).where(Upstream.id == target.id).values(is_default=True)
        )
        await self.session.commit()
        await self.session.refresh(target)
        return target

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
