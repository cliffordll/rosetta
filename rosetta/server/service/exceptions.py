"""Service 层 domain exception。

service 层不依赖 HTTP / FastAPI;所有需要映射成客户端错误响应的情况,抛 `ServiceError`,
由 controller 层的 `exception_handler` 统一转成 `HTTPException` + `rosetta_error` body。

`status` / `code` / `message` 三元组对应原 `rosetta_error` + HTTP status 的组合:
- `status`:HTTP status code(400 / 500 / 502 等)
- `code`:`rosetta_error` 的错因枚举(`invalid_json_body` / `translation_failed` / ...)
- `message`:人读 message
- `extra`:合进 error body 的附加字段(例:`stateful_not_translatable` 带 `field=<name>`)
"""

from __future__ import annotations

from typing import Any


class ServiceError(Exception):
    def __init__(
        self,
        *,
        status: int,
        code: str,
        message: str,
        **extra: Any,
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra
        super().__init__(message)
