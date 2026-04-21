"""数据面 /v1/* 路由汇总。"""

from __future__ import annotations

from fastapi import APIRouter

from rosetta.server.dataplane import routes

dataplane_router = APIRouter()
dataplane_router.include_router(routes.router)
