"""UpstreamRepo:upstreams 表的数据访问。

不抛 `HTTPException` —— 返回 None / 传递 `IntegrityError`,调用方决定 HTTP 语义。

`MOCK_UPSTREAM_FIELDS` 是内置 mock 上游的固定身份字段,`migrations/001_init.sql`
的 seed 和 `restore_mock` 都按它来,保证 id / name / provider 跨场景一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from types import EllipsisType
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import (
    ApiType,
    Setting,
    Upstream,
    default_upstream_key,
)

MOCK_UPSTREAM_FIELDS: dict[str, Any] = {
    "id": "0" * 32,
    "name": "mock",
    "native_api": "any",  # mock 不发 HTTP,native_api 字段语义不适用
    "provider": "mock",
    "base_url": "mock://",
    "api_key": None,
    "model": None,  # mock 路径不走 forwarder model fallback;client 自带
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
        - api_key / model 用 sentinel `...`(Ellipsis) 区分"传 None 显式清空"和
          "未传保持原值";其他字段用 None 即"未传"
        - `is_default` 已迁到 `settings` 表按 server_api 维护;改 native_api 后若该
          upstream 仍是某 server_api 的 default,selector 会按新的 native_api 查找
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

    async def default_upstream_id(self, server_api: str) -> str | None:
        """从 settings 表读指定 server_api 的 default upstream id;没有则读 global。"""
        setting = await self.session.get(Setting, default_upstream_key(server_api))
        if setting is not None:
            return setting.value
        global_setting = await self.session.get(Setting, "default_upstream_id")
        return global_setting.value if global_setting is not None else None

    async def get_default(self, server_api: str) -> Upstream | None:
        """查指定 server_api 的 enabled default upstream。

        优先级:
          1. settings['default_upstream_id:<server_api>']
          2. settings['default_upstream_id']
          3. 都没有 / 命中但被禁 → None
        """
        upstream_id = await self.default_upstream_id(server_api)
        if upstream_id is None:
            return None
        upstream = await self.get_by_id(upstream_id)
        if upstream is None or not upstream.enabled:
            return None
        return upstream

    async def list_defaults(self) -> dict[str, str | None]:
        """返回 global + per-server_api 的默认 upstream name 绑定。"""
        defaults: dict[str, str | None] = {}
        for scope, upstream_id in (
            ("global", await self._setting_value("default_upstream_id")),
            ("messages", await self._setting_value(default_upstream_key("messages"))),
            ("completions", await self._setting_value(default_upstream_key("completions"))),
            ("responses", await self._setting_value(default_upstream_key("responses"))),
        ):
            if upstream_id is None:
                defaults[scope] = None
                continue
            upstream = await self.get_by_id(upstream_id)
            defaults[scope] = upstream.name if upstream is not None else None
        return defaults

    async def set_default(
        self, name: str, server_api: str | None = None
    ) -> Upstream:
        """把 `name` 设为 default;写入 `settings` 表。

        - `server_api` 给值 → 设 per-server_api default
        - `server_api` 为 None → 设 global default
        - name 不存在 → `LookupError`(调用方转 404)
        - mock 行(native_api='any')也允许设 default
        """
        target = await self.get_by_name(name)
        if target is None:
            raise LookupError(f"upstream name={name!r} 不存在")

        key = (
            default_upstream_key(server_api)
            if server_api is not None
            else "default_upstream_id"
        )
        await self.session.merge(Setting(key=key, value=target.id))
        await self.session.commit()
        return target

    async def _setting_value(self, key: str) -> str | None:
        setting = await self.session.get(Setting, key)
        return setting.value if setting is not None else None

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
