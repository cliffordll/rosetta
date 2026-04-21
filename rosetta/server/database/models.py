"""SQLAlchemy 声明式 ORM 模型。

与 `migrations/001_init.sql` 字段对齐;SQL 是 schema 真源,ORM 镜像它。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ProviderType = Literal["anthropic", "openai", "openrouter", "custom"]
LogStatus = Literal["ok", "error", "timeout"]


class Base(DeclarativeBase):
    pass


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
    type: Mapped[str]
    base_url: Mapped[str | None] = mapped_column(default=None)
    api_key: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model_glob: Mapped[str]
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"))
    priority: Mapped[int] = mapped_column(default=0)


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"), default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    input_tokens: Mapped[int | None] = mapped_column(default=None)
    output_tokens: Mapped[int | None] = mapped_column(default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str]
    error: Mapped[str | None] = mapped_column(default=None)

    __table_args__ = (Index("idx_logs_created_at", "created_at"),)
