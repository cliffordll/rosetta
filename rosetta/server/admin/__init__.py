"""/admin/* 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from rosetta.server.admin import health, logs, providers, routes, shutdown, stats

admin_router = APIRouter()
admin_router.include_router(health.router)
admin_router.include_router(providers.router)
admin_router.include_router(routes.router)
admin_router.include_router(logs.router)
admin_router.include_router(stats.router)
admin_router.include_router(shutdown.router)
