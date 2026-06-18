"""数据面 upstream 选择。

两段策略(显式优先 + ServerApi default fallback,DESIGN §8.4):

1. `x-rosetta-upstream: <name>` header 有值 → 按 name 精确匹配
   - 不存在 → 400 `upstream_not_found`
   - 被禁用 → 400 `upstream_disabled`
2. header 缺失 → 按入口路径的 `server_api` 找 enabled 的 `is_default=True` 行
   - 命中 → 用它
   - 没设 default(或 default 被禁) → 400 `missing_rosetta_upstream`

跨 API 类型桥接是显式禁止的:fallback 严格按入口 server_api 找同 API 类型的 default,
不允许跨 API 类型借用(避免隐式 IR 翻译路径)。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Upstream
from rosetta.server.repository import UpstreamRepo
from rosetta.server.service.exceptions import ServiceError
from rosetta.shared.server_api import ServerApi


async def pick_upstream(
    session: AsyncSession,
    *,
    header_upstream: str | None,
    server_api: ServerApi,
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

    default = await repo.get_default(server_api.value)
    if default is None:
        raise ServiceError(
            status=400,
            code="missing_rosetta_upstream",
            message=(
                f"未传 x-rosetta-upstream header 且 server_api={server_api.value} "
                "无可用 default upstream"
            ),
        )
    return default
