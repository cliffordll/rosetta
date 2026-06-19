from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from rosetta.server.database.models import Setting
from rosetta.server.logs_config import (
    LOG_CONTENT_KEY,
    LOGS_PAGE_SIZE_KEY,
    LogsConfig,
    LogsPageSize,
    normalize_log_content,
    normalize_logs_page_size,
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
            page_size=normalize_logs_page_size(await self.get(LOGS_PAGE_SIZE_KEY)),
        )

    async def update_logs_config(
        self,
        *,
        log_content: str | None = None,
        page_size: LogsPageSize | None = None,
    ) -> LogsConfig:
        current = await self.get_logs_config()
        next_log_content = normalize_log_content(log_content or current.log_content)
        next_page_size = normalize_logs_page_size(
            current.page_size if page_size is None else page_size
        )
        await self.set(LOG_CONTENT_KEY, next_log_content)
        await self.set(LOGS_PAGE_SIZE_KEY, str(next_page_size))
        await self.session.commit()
        return LogsConfig(log_content=next_log_content, page_size=next_page_size)
