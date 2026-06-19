"""SQLAlchemy 声明式 ORM 模型。

与 `migrations/*.sql` 字段对齐;SQL 是 schema 真源,ORM 镜像它。

`Upstream.native_api` 对齐内置 API 类型枚举值:
`messages` / `completions` / `responses`,与 upstream 原生 HTTP path 一致。
额外有一个特殊值 `any`,专供 mock 上游占位 —— 表示"API 类型不适用"(mock 不发 HTTP,
也不走 adapter 的 upstream native API 分支);用户不可通过管理 API / CLI 创建 `any`
的 upstream,只由 DB seed / `restore_mock` 写入。

`Upstream.provider` 表达厂商身份(anthropic / openai / openrouter / google /
ollama / vllm / custom / mock),默认 `custom`。native_api 和 provider 正交:
OpenRouter 既可能暴露 `messages` 也可能暴露 `completions`,靠两字段独立描述。
`mock` 是内置的假上游(DB seed 一条 name=mock 的记录),forwarder 检测到后
短路掉 HTTP,本地生成 echo 响应供开发 / 演示。

主键:`id` 是 32 字符 UUID4 hex,由 `default=` 在插入时生成。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_UPSTREAM_KEY_PREFIX = "default_upstream_id"


def default_upstream_key(server_api: str) -> str:
    """settings 表中某个 server_api 的 default upstream key。"""
    return f"{DEFAULT_UPSTREAM_KEY_PREFIX}:{server_api}"

UpstreamNativeApi = Literal["messages", "completions", "responses", "any"]
UpstreamProvider = Literal[
    "anthropic",
    "openai",
    "openrouter",
    "google",
    "ollama",
    "vllm",
    "custom",
    "mock",
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
    native_api: Mapped[str]
    provider: Mapped[str] = mapped_column(default="custom")
    base_url: Mapped[str]
    api_key: Mapped[str | None] = mapped_column(default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class Setting(Base):
    """通用 key-value 配置表。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[str]


class ApiType(Base):
    __tablename__ = "api_types"

    name: Mapped[str] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(unique=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[str] = mapped_column(primary_key=True, default=_new_id)
    upstream_id: Mapped[str | None] = mapped_column(ForeignKey("upstreams.id"), default=None)
    model: Mapped[str | None] = mapped_column(default=None)
    input_tokens: Mapped[int | None] = mapped_column(default=None)
    output_tokens: Mapped[int | None] = mapped_column(default=None)
    latency_ms: Mapped[int | None] = mapped_column(default=None)
    status: Mapped[str]
    error: Mapped[str | None] = mapped_column(default=None)
    # 客户端 "host:port"(FastAPI request.client);本机回环也记
    client_addr: Mapped[str | None] = mapped_column(default=None)
    # upstream.base_url 快照(mock 路径写 'mock://');不与 upstream 外键联动,
    # 后续编辑 upstream.base_url 不影响历史 log
    upstream_url: Mapped[str | None] = mapped_column(default=None)
    request_text: Mapped[str | None] = mapped_column(default=None)
    response_text: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    __table_args__ = (Index("idx_logs_created_at", "created_at"),)
