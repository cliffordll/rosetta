"""SQLAlchemy 声明式 ORM 模型。

与 `migrations/*.sql` 字段对齐;SQL 是 schema 真源,ORM 镜像它。

`Upstream.protocol` 对齐 `rosetta.shared.protocols.Protocol` 枚举值:
`messages` / `completions` / `responses`,与 CLI `--protocol` / HTTP path 四层一致。

`Upstream.provider` 表达厂商身份(anthropic / openai / openrouter / google /
ollama / vllm / custom),默认 `custom`。protocol 和 provider 正交:
OpenRouter 既可能暴露 `messages` 也可能暴露 `completions`,靠两字段独立描述。

主键:`id` 是 32 字符 UUID4 hex,由 `default=` 在插入时生成。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

UpstreamProtocol = Literal["messages", "completions", "responses"]
UpstreamProvider = Literal[
    "anthropic",
    "openai",
    "openrouter",
    "google",
    "ollama",
    "vllm",
    "custom",
]
LogStatus = Literal["ok", "error", "timeout"]


def _new_id() -> str:
    """32 字符 UUID4 hex(无连字符)。"""
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class Upstream(Base):
    __tablename__ = "upstreams"

    id: Mapped[str] = mapped_column(primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(unique=True)
    protocol: Mapped[str]
    provider: Mapped[str] = mapped_column(default="custom")
    base_url: Mapped[str]
    api_key: Mapped[str | None] = mapped_column(default=None)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[str] = mapped_column(primary_key=True, default=_new_id)
    upstream_id: Mapped[str | None] = mapped_column(
        ForeignKey("upstreams.id"), default=None
    )
    model: Mapped[str | None] = mapped_column(default=None)
    input_tokens: Mapped[int | None] = mapped_column(default=None)
    output_tokens: Mapped[int | None] = mapped_column(default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str]
    error: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (Index("idx_logs_created_at", "created_at"),)
