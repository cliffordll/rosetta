"""数据面 upstream 选择。

两段策略(显式优先 + per-server_api default + global default fallback):

1. `r-upstream: <name>` header 有值 → 按 name 精确匹配
   - 不存在 → 400 `upstream_not_found`
   - 被禁用 → 400 `upstream_disabled`
2. header 缺失 → 按入口 server_api 找 default
   - 先查 `settings['default_upstream_id:<server_api>']`
   - 没有 → 查 `settings['default_upstream_id']`
   - 命中 → 用它
   - 都没设(或 default 被禁) → 400 `missing_rosetta_upstream`

default 的 native_api 可与入口 server_api 不同,由 forwarder 走 IR 翻译路径。
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
                message=f"r-upstream 指定的 '{header_upstream}' 不存在",
            )
        if not upstream.enabled:
            raise ServiceError(
                status=400,
                code="upstream_disabled",
                message=f"r-upstream 指定的 '{header_upstream}' 被禁用",
            )
        return upstream

    default = await repo.get_default(server_api.value)
    if default is None:
        raise ServiceError(
            status=400,
            code="missing_rosetta_upstream",
            message=f"未传 r-upstream header 且 server_api={server_api.value} "
            "无可用 default upstream",
        )
    return default
