"""Controller 层:所有 HTTP endpoint 汇总 + 异常映射。

两组 router 对外暴露,app.py 分别挂到不同 prefix:

- `admin_router`(挂在 `/admin`):管理面 —— runtime / providers / logs / stats
- `dataplane_router`(无 prefix,端点内含 `/v1/*`):数据面 —— messages / chat / responses

分层约定:controller 负责 HTTP 协议(参数解析、状态码、错误映射);
business 逻辑在 `rosetta.server.service`(forwarder / selector)和 `repository`;
错误工厂在 `rosetta.server.controller.errors`。

`register_exception_handlers(app)` 注册 service 层 `ServiceError` → HTTP 响应的统一映射。
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from rosetta.server.controller import dataplane, logs, providers, runtime, stats
from rosetta.server.controller.errors import rosetta_error
from rosetta.server.service.exceptions import ServiceError

admin_router = APIRouter()
admin_router.include_router(runtime.router)
admin_router.include_router(providers.router)
admin_router.include_router(logs.router)
admin_router.include_router(stats.router)

dataplane_router = APIRouter()
dataplane_router.include_router(dataplane.router)


def register_exception_handlers(app: FastAPI) -> None:
    """把 service 层的 `ServiceError` 映射成统一的 rosetta_error HTTP 响应。"""

    @app.exception_handler(ServiceError)
    async def _handle_service_error(
        _request: Request, exc: ServiceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=rosetta_error(exc.code, exc.message, **exc.extra),
        )


__all__ = ["admin_router", "dataplane_router", "register_exception_handlers"]
