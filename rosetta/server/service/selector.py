"""数据面 upstream 选择。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError


async def pick_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
    model: str | None,
) -> Upstream:
    """按 r-upstream / model 三阶段选择 upstream。"""
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
        return upstream

    if model:
        upstreams = await repo.get_by_model(model)
        if len(upstreams) == 1:
            return upstreams[0]
        if not upstreams:
            raise ServiceError(
                status=400,
                code="no_upstream_for_model",
                message=f"未找到 model='{model}' 对应的 upstream",
            )
        default_id = await repo.default_model_upstream_id(model)
        if default_id is not None:
            for upstream in upstreams:
                if upstream.id == default_id:
                    return upstream
        raise ServiceError(
            status=400,
            code="model_ambiguous",
            message=f"model='{model}' 匹配到多个 upstream,请配置 model 默认或传 r-upstream",
        )

    raise ServiceError(
        status=400,
        code="missing_routing_info",
        message="未传 r-upstream header 且请求 body 缺少 model,无法选择 upstream",
    )
