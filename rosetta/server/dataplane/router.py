"""数据面 provider 选择(DESIGN §8.4 的 7 条 rule)。

规则
----
1. 取请求体的 `model` 字段
2. header `x-rosetta-provider: <name>` 存在 → 按 name 精确匹配(跳过 3-5)
3. 按 `(priority ASC, id ASC)` 遍历 `routes` 表
4. 第一条 `fnmatch(model, model_glob)` 命中的 route → 选它的 provider
5. 都不匹配 → 选第一个 enabled 的 provider(兜底)
6. 选中的 provider 不存在 / 被禁用:
   - rule 2(header 指定)→ 400(客户端自己填错了)
   - rule 4(routes 命中)→ 503(配置问题)
7. 连一个 enabled 的 provider 都没有 → 503 `no_provider_available`

503 / 400 错误体一律用 `rosetta_error` 结构(DESIGN §8.4):
`{"error": {"type": "rosetta_error", "code": "...", "message": "..."}}`

异格式回退自动翻译
------------------
本模块只负责 **选 provider**,不管格式。选中后由 `forwarder.forward` 根据
`provider.type` 与 `request_format` 一致与否决定直通 / 走翻译(阶段 2.3 接线已就位)。
"""

from __future__ import annotations

import json
from fnmatch import fnmatch
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Provider, Route


def _rosetta_error(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"type": "rosetta_error", "code": code, "message": message}}


def parse_model(body: bytes) -> str | None:
    """从 JSON 请求体抽 model 字段;解析失败 / 非 dict / 字段缺失 / 非 str → None。"""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    model = cast(dict[str, Any], data).get("model")
    return model if isinstance(model, str) else None


async def pick_provider(
    session: AsyncSession,
    *,
    model: str | None,
    header_provider: str | None,
) -> Provider:
    # rule 2:header 短路
    if header_provider:
        result = await session.execute(select(Provider).where(Provider.name == header_provider))
        provider = result.scalar_one_or_none()
        if provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_rosetta_error(
                    "provider_not_found",
                    f"x-rosetta-provider 指定的 '{header_provider}' 不存在",
                ),
            )
        if not provider.enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_rosetta_error(
                    "provider_disabled",
                    f"x-rosetta-provider 指定的 '{header_provider}' 被禁用",
                ),
            )
        return provider

    # rule 3-4:routes 表按 (priority ASC, id ASC) 扫
    if model:
        routes_result = await session.execute(select(Route).order_by(Route.priority, Route.id))
        for route in routes_result.scalars().all():
            if not fnmatch(model, route.model_glob):
                continue
            provider = await session.get(Provider, route.provider_id)
            # rule 6:命中但 provider 不可用 → 503(不降级到 rule 5)
            if provider is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=_rosetta_error(
                        "provider_not_found",
                        f"route '{route.model_glob}' 指向的 provider_id="
                        f"{route.provider_id} 已不存在",
                    ),
                )
            if not provider.enabled:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=_rosetta_error(
                        "provider_disabled",
                        f"route '{route.model_glob}' 命中 provider '{provider.name}',"
                        f"但该 provider 被禁用",
                    ),
                )
            return provider

    # rule 5:兜底第一个 enabled provider(按 id 稳定序)
    fallback_result = await session.execute(
        select(Provider).where(Provider.enabled.is_(True)).order_by(Provider.id).limit(1)
    )
    provider = fallback_result.scalar_one_or_none()
    if provider is not None:
        return provider

    # rule 7
    msg = (
        f"no enabled provider matches model '{model}'" if model else "no enabled provider available"
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_rosetta_error("no_provider_available", msg),
    )
