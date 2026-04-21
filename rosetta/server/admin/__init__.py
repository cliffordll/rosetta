"""/admin/* 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from rosetta.server.admin import health

admin_router = APIRouter()
admin_router.include_router(health.router)
