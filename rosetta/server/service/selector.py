"""数据面 upstream 选择。

策略简化为 header 强制:客户端必须通过 `x-rosetta-upstream: <name>` header 显式
指定 upstream;没 header / upstream 不存在 / 被禁用都抛 `ServiceError(status=400, ...)`,
由 controller 层统一转 HTTP 响应。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError


async def pick_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
) -> Upstream:
    if not header_upstream:
        raise ServiceError(
            status=400,
            code="missing_rosetta_upstream",
            message="缺少 x-rosetta-upstream header;必须显式指定 upstream",
        )
    upstream = await UpstreamRepo(session).get_by_name(header_upstream)
    if upstream is None:
        raise ServiceError(
            status=400,
            code="upstream_not_found",
            message=f"x-rosetta-upstream 指定的 '{header_upstream}' 不存在",
        )
    if not upstream.enabled:
        raise ServiceError(
            status=400,
            code="upstream_disabled",
            message=f"x-rosetta-upstream 指定的 '{header_upstream}' 被禁用",
        )
    return upstream
