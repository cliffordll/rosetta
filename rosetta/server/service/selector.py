"""数据面 provider 选择。

策略简化为 header 强制:客户端必须通过 `x-rosetta-provider: <name>` header 显式
指定 provider;没 header / provider 不存在 / 被禁用都抛 `ServiceError(status=400, ...)`,
由 controller 层统一转 HTTP 响应。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider
from rosetta.server.repository import ProviderRepo
from rosetta.server.service.exceptions import ServiceError


async def pick_provider(
    session: AsyncSession,
    *,
    header_provider: str | None,
) -> Provider:
    if not header_provider:
        raise ServiceError(
            status=400,
            code="missing_rosetta_provider",
            message="缺少 x-rosetta-provider header;必须显式指定 provider",
        )
    provider = await ProviderRepo(session).get_by_name(header_provider)
    if provider is None:
        raise ServiceError(
            status=400,
            code="provider_not_found",
            message=f"x-rosetta-provider 指定的 '{header_provider}' 不存在",
        )
    if not provider.enabled:
        raise ServiceError(
            status=400,
            code="provider_disabled",
            message=f"x-rosetta-provider 指定的 '{header_provider}' 被禁用",
        )
    return provider
