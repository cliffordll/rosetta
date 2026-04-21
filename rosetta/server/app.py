"""FastAPI app 工厂。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rosetta import __version__
from rosetta.server.admin import admin_router
from rosetta.server.dataplane import dataplane_router
from rosetta.server.dataplane.forwarder import dispose_client, init_client
from rosetta.server.db.session import dispose_db, init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await init_client()
    try:
        yield
    finally:
        await dispose_client()
        await dispose_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="rosetta",
        version=__version__,
        description="本地 LLM API 格式转换中枢(admin + data plane)",
        lifespan=lifespan,
    )
    app.include_router(admin_router, prefix="/admin")
    app.include_router(dataplane_router)
    return app
