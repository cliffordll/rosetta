"""FastAPI app 工厂。"""

from __future__ import annotations

from fastapi import FastAPI

from rosetta import __version__
from rosetta.server.admin import admin_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="rosetta",
        version=__version__,
        description="本地 LLM API 格式转换中枢(admin + data plane)",
    )
    app.include_router(admin_router, prefix="/admin")
    return app
