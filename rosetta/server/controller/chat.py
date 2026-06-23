"""/admin/chat/config: chat page override settings persistence.
GET  /admin/chat/config  -> ChatConfigOut
PUT  /admin/chat/config  <- ChatConfigUpdate -> ChatConfigOut
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from rosetta.server.repository import SettingsRepoDep

router = APIRouter()


class ChatConfigOut(BaseModel):
    max_tokens: int
    stream: bool


class ChatConfigUpdate(BaseModel):
    max_tokens: int | None = None
    stream: bool | None = None


@router.get("/chat/config", response_model=ChatConfigOut)
async def get_chat_config(settings_repo: SettingsRepoDep) -> ChatConfigOut:
    config = await settings_repo.get_chat_config()
    return ChatConfigOut(max_tokens=config.max_tokens, stream=config.stream)


@router.put("/chat/config", response_model=ChatConfigOut)
async def update_chat_config(
    payload: ChatConfigUpdate,
    settings_repo: SettingsRepoDep,
) -> ChatConfigOut:
    if payload.max_tokens is None and payload.stream is None:
        config = await settings_repo.get_chat_config()
        return ChatConfigOut(max_tokens=config.max_tokens, stream=config.stream)
    config = await settings_repo.update_chat_config(
        max_tokens=payload.max_tokens,
        stream=payload.stream,
    )
    return ChatConfigOut(max_tokens=config.max_tokens, stream=config.stream)
