from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Setting
from rosetta.server.logs_config import (
    CHAT_MAX_TOKENS_KEY,
    CHAT_STREAM_KEY,
    LOG_CONTENT_KEY,
    LOGS_PAGE_SIZE_KEY,
    ChatConfig,
    LogsConfig,
    LogsPageSize,
    normalize_chat_max_tokens,
    normalize_chat_stream,
    normalize_log_content,
    normalize_log_page_size,
)


class SettingsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> str | None:
        setting = await self.session.get(Setting, key)
        return setting.value if setting is not None else None

    async def set(self, key: str, value: str) -> None:
        await self.session.merge(Setting(key=key, value=value))

    async def get_logs_config(self) -> LogsConfig:
        return LogsConfig(
            log_content=normalize_log_content(await self.get(LOG_CONTENT_KEY)),
            page_size=normalize_log_page_size(await self.get(LOGS_PAGE_SIZE_KEY)),
        )

    async def update_logs_config(
        self,
        *,
        log_content: str | None = None,
        page_size: LogsPageSize | None = None,
    ) -> LogsConfig:
        current = await self.get_logs_config()
        next_log_content = normalize_log_content(log_content or current.log_content)
        next_page_size = normalize_log_page_size(
            current.page_size if page_size is None else page_size
        )
        await self.set(LOG_CONTENT_KEY, next_log_content)
        await self.set(LOGS_PAGE_SIZE_KEY, str(next_page_size))
        await self.session.commit()
        return LogsConfig(log_content=next_log_content, page_size=next_page_size)

    async def get_chat_config(self) -> ChatConfig:
        return ChatConfig(
            max_tokens=normalize_chat_max_tokens(await self.get(CHAT_MAX_TOKENS_KEY)),
            stream=normalize_chat_stream(await self.get(CHAT_STREAM_KEY)),
        )

    async def update_chat_config(
        self,
        *,
        max_tokens: int | None = None,
        stream: bool | None = None,
    ) -> ChatConfig:
        current = await self.get_chat_config()
        next_max_tokens = max_tokens if max_tokens is not None else current.max_tokens
        next_stream = stream if stream is not None else current.stream
        await self.set(CHAT_MAX_TOKENS_KEY, str(next_max_tokens))
        await self.set(CHAT_STREAM_KEY, str(next_stream).lower())
        await self.session.commit()
        return ChatConfig(max_tokens=next_max_tokens, stream=next_stream)
