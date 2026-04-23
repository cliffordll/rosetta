"""FastAPI app 工厂。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rosetta import __version__
from rosetta.server.controller import (
    admin_router,
    dataplane_router,
    register_exception_handlers,
)
from rosetta.server.database.session import dispose_db, init_db
from rosetta.server.service.forwarder import forwarder

_log = logging.getLogger("rosetta.server.app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _log.info("starting rosetta v%s (init db + forwarder)", __version__)
    await init_db()
    await forwarder.open()
    _log.info("startup complete")
    try:
        yield
    finally:
        _log.info("shutdown: closing forwarder + db")
        await forwarder.close()
        await dispose_db()
        _log.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="rosetta",
        version=__version__,
        description="本地 LLM API 格式转换中枢(admin + data plane)",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/admin")
    app.include_router(dataplane_router)
    return app
