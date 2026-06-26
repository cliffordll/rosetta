"""数据面 upstream 选择。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError
from rosetta.shared.server_api import ServerApi


@dataclass(frozen=True)
class UpstreamSelection:
    upstream: Upstream
    rewrite_model_to_upstream: bool = False


async def pick_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
    model: str | None,
    setup_scope: str | None = None,
) -> Upstream:
    return (
        await select_upstream(
            session,
            header_upstream=header_upstream,
            model=model,
            setup_scope=setup_scope,
        )
    ).upstream


async def select_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
    model: str | None,
    setup_scope: str | None = None,
) -> UpstreamSelection:
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
        return UpstreamSelection(upstream)

    if model:
        default_id = await repo.default_model_upstream_id(model)
        if default_id is not None:
            upstream = await repo.get_by_id(default_id)
            if upstream is not None and upstream.enabled:
                rewrite = bool(upstream.model and upstream.model.strip() != model)
                return UpstreamSelection(upstream, rewrite_model_to_upstream=rewrite)

        setup_alias_id = (
            await repo.setup_model_alias_upstream_id(setup_scope, model)
            if setup_scope is not None
            else None
        )
        if setup_alias_id is not None:
            upstream = await repo.get_by_id(setup_alias_id)
            if upstream is not None and upstream.enabled:
                rewrite = bool(upstream.model and upstream.model.strip() != model)
                return UpstreamSelection(upstream, rewrite_model_to_upstream=rewrite)

        upstreams = await repo.get_by_model(model)
        if len(upstreams) == 1:
            return UpstreamSelection(upstreams[0])
        if not upstreams:
            raise ServiceError(
                status=400,
                code="no_upstream_for_model",
                message=f"未找到 model='{model}' 对应的 upstream",
            )
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


def setup_scope_for_server_api(server_api: ServerApi) -> str:
    if server_api is ServerApi.RESPONSES:
        return "codex"
    if server_api is ServerApi.MESSAGES:
        return "claude"
    return "opencode"