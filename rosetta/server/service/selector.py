"""数据面 upstream 选择。

两段策略(显式优先 + protocol default fallback,DESIGN §8.4):

1. `x-rosetta-upstream: <name>` header 有值 → 按 name 精确匹配
   - 不存在 → 400 `upstream_not_found`
   - 被禁用 → 400 `upstream_disabled`
2. header 缺失 → 按入口路径的 `request_protocol` 找 enabled 的 `is_default=True` 行
   - 命中 → 用它
   - 没设 default(或 default 被禁) → 400 `missing_rosetta_upstream`

跨协议桥接是显式禁止的:fallback 严格按入口 protocol 找同 protocol 的 default,
不允许跨协议借用(避免隐式 IR 翻译路径)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError
from rosetta.shared.protocols import Protocol


async def pick_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
    request_protocol: Protocol,
) -> Upstream:
    repo = UpstreamRepo(session)

    if header_upstream:
        upstream = await repo.get_by_name(header_upstream)
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

    default = await repo.get_default(request_protocol.value)
    if default is None:
        raise ServiceError(
            status=400,
            code="missing_rosetta_upstream",
            message=(
                f"未传 x-rosetta-upstream header 且 protocol={request_protocol.value} "
                "无可用 default upstream"
            ),
        )
    return default
