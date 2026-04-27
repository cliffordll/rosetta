"""LogRepo:logs 表的数据访问 + 按窗口聚合统计。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import LogEntry, Upstream


class LogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        upstream_id: str | None,
        model: str | None,
        status: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
        error: str | None = None,
        client_addr: str | None = None,
        upstream_url: str | None = None,
    ) -> LogEntry:
        """插入一条 log;调用方保证字段语义(status ∈ {ok, error, timeout})。"""
        entry = LogEntry(
            upstream_id=upstream_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status=status,
            error=error,
            client_addr=client_addr,
            upstream_url=upstream_url,
        )
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    @staticmethod
    def _build_filters(
        *,
        upstream_id: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> list[ColumnElement[bool]]:
        """三个 list / count 共用的 where 条件。`since` 是严格大于,服务 polling 游标。"""
        filters: list[ColumnElement[bool]] = []
        if upstream_id is not None:
            filters.append(LogEntry.upstream_id == upstream_id)
        if since is not None:
            filters.append(LogEntry.created_at > since)
        if until is not None:
            filters.append(LogEntry.created_at <= until)
        return filters

    async def list_with_upstream(
        self,
        *,
        limit: int,
        offset: int,
        upstream_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[tuple[LogEntry, Upstream | None]]:
        """按条件查 log + outer-join upstream name;死引用 upstream 那侧返回 None。"""
        filters = self._build_filters(upstream_id=upstream_id, since=since, until=until)

        stmt = (
            select(LogEntry, Upstream)
            .outerjoin(Upstream, LogEntry.upstream_id == Upstream.id)
            .order_by(LogEntry.created_at.desc(), LogEntry.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if filters:
            stmt = stmt.where(and_(*filters))

        result = await self.session.execute(stmt)
        # Row → tuple 显式解构:pyright 不把 Sequence[Row[Tuple[A,B]]] 看作
        # Sequence[tuple[A, B|None]](协变不成立),手动 unpack 后类型就对了
        return [(entry, up) for entry, up in result.all()]

    async def count_with_filters(
        self,
        *,
        upstream_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> int:
        """同 `list_with_upstream` 的 where 条件下统计总数,服务分页器算 totalPages。"""
        filters = self._build_filters(upstream_id=upstream_id, since=since, until=until)
        stmt = select(func.count(LogEntry.id))
        if filters:
            stmt = stmt.where(and_(*filters))
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

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
