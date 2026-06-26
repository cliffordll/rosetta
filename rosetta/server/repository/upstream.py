"""UpstreamRepo:upstreams 表的数据访问。

不抛 `HTTPException` —— 返回 None / 传递 `IntegrityError`,调用方决定 HTTP 语义。

`MOCK_UPSTREAM_FIELDS` 是内置 mock 上游的固定身份字段,`migrations/001_init.sql`
的 seed 和 `restore_mock` 都按它来,保证 id / name / provider 跨场景一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from types import EllipsisType
from typing import Any, TypedDict

from sqlalchemy import delete, func, select
from sqlalchemy import update as _update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Model, Upstream, UpstreamModel


class ModelListRow(TypedDict):
    id: str
    name: str
    alias: str | None
    enabled: bool
    upstreams: str
    has_default: bool
MOCK_UPSTREAM_FIELDS: dict[str, Any] = {
    "id": "0" * 32,
    "name": "mock",
    "native_api": "any",
    "provider": "mock",
    "base_url": "mock://",
    "api_key": None,
    "model": "mock-default",
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

    async def get_by_model(self, model: str) -> Sequence[Upstream]:
        result = await self.session.execute(
            select(Upstream)
            .where(Upstream.model == model, Upstream.enabled.is_(True))
            .order_by(Upstream.created_at, Upstream.id)
        )
        return result.scalars().all()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count()).select_from(Upstream))
        return int(result.scalar_one())

    async def select_upstream_by_model(
        self, model: str
    ) -> tuple[Upstream | None, str | None, str | None]:
        """Find enabled upstream for a canonical model name or public alias.

        Returns (upstream, public_alias, rewrite_model_to). rewrite_model_to is set
        only when the input matched Model.alias, so the upstream receives its real model.
        """
        stmt = (
            select(Upstream, Model.name, Model.alias)
            .join(UpstreamModel, UpstreamModel.upstream_id == Upstream.id)
            .join(Model, Model.id == UpstreamModel.model_id)
            .where((Model.name == model) | (Model.alias == model))
            .where(Model.enabled.is_(True))
            .where(Upstream.enabled.is_(True))
            .order_by((Model.alias == model).desc(), UpstreamModel.is_default.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return (None, None, None)
        rewrite_model_to = (
            row.Upstream.model if row.alias == model and row.name != model else None
        )
        return (row.Upstream, row.alias, rewrite_model_to)

    async def list_models(self) -> list[ModelListRow]:
        """List all models with alias, enabled, and upstream info."""
        from sqlalchemy import func as _func

        stmt = (
            select(
                Model.id,
                Model.name,
                Model.alias,
                Model.enabled,
                _func.group_concat(Upstream.name, ", ").label("upstreams"),
                _func.sum(UpstreamModel.is_default).label("has_default"),
            )
            .outerjoin(UpstreamModel, UpstreamModel.model_id == Model.id)
            .outerjoin(Upstream, Upstream.id == UpstreamModel.upstream_id)
            .group_by(Model.id)
            .order_by(Model.name)
        )
        result = await self.session.execute(stmt)
        rows: list[ModelListRow] = []
        for row in result.all():
            rows.append(
                {
                    "id": str(row.id),
                    "name": str(row.name),
                    "alias": row.alias if isinstance(row.alias, str) else None,
                    "enabled": bool(row.enabled),
                    "upstreams": str(row.upstreams or ""),
                    "has_default": bool(row.has_default),
                }
            )
        return rows

    async def list_model_defaults(self) -> dict[str, str]:
        stmt = (
            select(Model.name, UpstreamModel.upstream_id)
            .join(UpstreamModel, UpstreamModel.model_id == Model.id)
            .where(UpstreamModel.is_default.is_(True))
            .order_by(Model.name)
        )
        result = await self.session.execute(stmt)
        return {str(row.name): str(row.upstream_id) for row in result.all()}

    async def set_model_alias(self, model_name: str, alias: str | None) -> None:
        """Set or clear the alias for a model name."""
        result = await self.session.execute(select(Model).where(Model.name == model_name))
        model = result.scalar_one_or_none()
        if model is None:
            raise LookupError(f"model={model_name!r} does not exist")
        model.alias = alias
        await self.session.commit()

    async def set_model_enabled(self, model_name: str, enabled: bool) -> None:
        """Enable or disable a model."""
        result = await self.session.execute(select(Model).where(Model.name == model_name))
        model = result.scalar_one_or_none()
        if model is None:
            raise LookupError(f"model={model_name!r} does not exist")
        model.enabled = enabled
        await self.session.commit()

    async def get_or_create_model(self, name: str, alias: str | None = None) -> str:
        """Get existing model id or create one. Returns model id."""
        result = await self.session.execute(select(Model).where(Model.name == name))
        model = result.scalar_one_or_none()
        if model is not None:
            return model.id
        model = Model(name=name, alias=alias)
        self.session.add(model)
        await self.session.commit()
        await self.session.refresh(model)
        return model.id

    async def set_upstream_model(
        self, upstream_id: str, model_id: str, is_default: bool = True
    ) -> None:
        """Link upstream to a model, optionally as default."""
        existing = await self.session.get(UpstreamModel, (upstream_id, model_id))
        if existing is None:
            self.session.add(
                UpstreamModel(upstream_id=upstream_id, model_id=model_id, is_default=is_default)
            )
        elif is_default:
            existing.is_default = True
        await self.session.commit()

    async def unset_other_defaults(self, model_name: str, keep_upstream_id: str) -> None:
        """Remove is_default from other upstreams linked to this model."""
        subq = select(Model.id).where(Model.name == model_name).scalar_subquery()
        stmt = (
            _update(UpstreamModel)
            .where(UpstreamModel.model_id == subq)
            .where(UpstreamModel.upstream_id != keep_upstream_id)
            .values(is_default=False)
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def create(
        self,
        *,
        name: str,
        native_api: str,
        provider: str,
        base_url: str,
        api_key: str | None,
        model: str,
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
        model: str | EllipsisType = ...,
        enabled: bool | None = None,
    ) -> Upstream:
        """部分更新 upstream;只改传入的字段。

        - id 不存在 → `LookupError`(调用方转 404)
        - name 冲突 → `IntegrityError`(调用方转 409)
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
        next_model: str | None = None
        if api_key is not ...:
            target.api_key = api_key
        if model is not ...:
            target.model = model
            next_model = model
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
        if next_model is not None:
            model_id = await self.get_or_create_model(next_model)
            await self.session.execute(
                delete(UpstreamModel)
                .where(UpstreamModel.upstream_id == upstream_id)
                .where(UpstreamModel.model_id != model_id)
            )
            await self.set_upstream_model(upstream_id, model_id, is_default=True)
            await self.unset_other_defaults(next_model, upstream_id)
            await self.session.refresh(target)
        return target

    async def delete(self, upstream: Upstream) -> None:
        await self.session.execute(
            delete(UpstreamModel).where(UpstreamModel.upstream_id == upstream.id)
        )
        orphan_model_ids = (
            select(Model.id)
            .outerjoin(UpstreamModel, UpstreamModel.model_id == Model.id)
            .group_by(Model.id)
            .having(func.count(UpstreamModel.upstream_id) == 0)
        )
        await self.session.execute(delete(Model).where(Model.id.in_(orphan_model_ids)))
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
