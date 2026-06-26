"""数据面 upstream 选择。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError


@dataclass(frozen=True)
class UpstreamSelection:
    upstream: Upstream
    alias: str | None = None
    rewrite_model_to: str | None = None


async def select_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
    model: str | None,
) -> UpstreamSelection:
    """按 r-upstream header / model 选择 upstream。

    路由优先级:
    1. r-upstream header (精确指定 upstream id)
    2. models JOIN upstream_models (取 is_default 排序的第一个 enabled upstream)
    """
    repo = UpstreamRepo(session)

    if header_upstream:
        upstream = await repo.get_by_id(header_upstream)
        if upstream is None:
            raise ServiceError(
                status=400,
                code="upstream_not_found",
                message=f"r-upstream 指定的 '{header_upstream}' 不存在",
            )
        if not upstream.enabled:
            raise ServiceError(
                status=400,
                code="upstream_disabled",
                message=f"r-upstream 指定的 '{header_upstream}' 被禁用",
            )
        return UpstreamSelection(upstream)

    if model:
        upstream, alias, rewrite_model_to = await repo.select_upstream_by_model(model)
        if upstream is None:
            raise ServiceError(
                status=400,
                code="no_upstream_for_model",
                message=f"未找到 model='{model}' 对应的 upstream(模型可能被禁用)",
            )
        return UpstreamSelection(upstream, alias=alias, rewrite_model_to=rewrite_model_to)

    raise ServiceError(
        status=400,
        code="missing_routing_info",
        message="未传 r-upstream header 且请求 body 缺少 model,无法选择 upstream",
    )
