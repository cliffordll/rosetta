"""Repository 层:封装 ORM 查询,endpoint / selector 按业务语义调用。

层次:
- `database/`:infra(engine / session / migrations / ORM 声明)
- `repository/`:data access(按表分类的 query helper)
- `admin/` / `dataplane/`:调用 repo,不直接写 SQLAlchemy

错误语义:repo **不抛** `HTTPException`。None / `IntegrityError` 等原始信号交给 endpoint,
让不同 caller(admin 走 404/409、selector 走 400)各自映射成 HTTP 错误。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from rosetta.server.database.session import SessionDep
from rosetta.server.repository.log import LogRepo
from rosetta.server.repository.provider import ProviderRepo


def _provider_repo(session: SessionDep) -> ProviderRepo:
    return ProviderRepo(session)


def _log_repo(session: SessionDep) -> LogRepo:
    return LogRepo(session)


ProviderRepoDep = Annotated[ProviderRepo, Depends(_provider_repo)]
LogRepoDep = Annotated[LogRepo, Depends(_log_repo)]

__all__ = [
    "LogRepo",
    "LogRepoDep",
    "ProviderRepo",
    "ProviderRepoDep",
]
