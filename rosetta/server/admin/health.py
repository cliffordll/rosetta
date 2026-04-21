"""admin 心跳:/admin/ping 和 /admin/status。"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from rosetta import __version__
from rosetta.server.db.session import count_providers

router = APIRouter()

_START_MONO = time.monotonic()


class PingResponse(BaseModel):
    ok: bool


class StatusResponse(BaseModel):
    version: str
    uptime_ms: int
    providers_count: int


@router.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    return PingResponse(ok=True)


@router.get("/status", response_model=StatusResponse)
async def status() -> StatusResponse:
    uptime_ms = int((time.monotonic() - _START_MONO) * 1000)
    providers_count = await count_providers()
    return StatusResponse(
        version=__version__,
        uptime_ms=uptime_ms,
        providers_count=providers_count,
    )
