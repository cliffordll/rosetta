"""LogRepo:logs 表的数据访问 + 按窗口聚合统计。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import LogEntry, Provider


class LogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_with_provider(
        self,
        *,
        limit: int,
        offset: int,
        provider_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[tuple[LogEntry, Provider | None]]:
        """按条件查 log + outer-join provider name;死引用 provider 那侧返回 None。"""
        filters: list[ColumnElement[bool]] = []
        if provider_id is not None:
            filters.append(LogEntry.provider_id == provider_id)
        if since is not None:
            filters.append(LogEntry.created_at >= since)
        if until is not None:
            filters.append(LogEntry.created_at <= until)

        stmt = (
            select(LogEntry, Provider)
            .outerjoin(Provider, LogEntry.provider_id == Provider.id)
            .order_by(LogEntry.created_at.desc(), LogEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(and_(*filters))

        result = await self.session.execute(stmt)
        return result.all()

    async def aggregate_stats(self, *, since: datetime) -> tuple[int, int, float]:
        """窗口内聚合;返回 (total, ok_count, avg_latency_ms)。无样本时各字段 0。"""
        stmt = select(
            func.count(LogEntry.id),
            func.coalesce(
                func.sum(case((LogEntry.status == "ok", 1), else_=0)),
                0,
            ),
            func.coalesce(func.avg(LogEntry.latency_ms), 0),
        ).where(LogEntry.created_at >= since)
        row = (await self.session.execute(stmt)).one()
        return int(row[0] or 0), int(row[1] or 0), float(row[2] or 0.0)
