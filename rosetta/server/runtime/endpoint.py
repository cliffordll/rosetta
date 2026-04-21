"""`~/.rosetta/endpoint.json` 读写 + 原子替换。

Server 启动写 url / token / pid,客户端读来发现 server。
写入用 `.tmp` → `os.replace` 保证原子,避免客户端读到半截文件。
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any, TypedDict, cast

ENDPOINT_PATH = Path.home() / ".rosetta" / "endpoint.json"
_TMP_PATH = ENDPOINT_PATH.parent / (ENDPOINT_PATH.name + ".tmp")


class Endpoint(TypedDict):
    url: str
    token: str
    pid: int


def write_endpoint(url: str, token: str, pid: int) -> None:
    """原子写入 endpoint.json(先 .tmp 再 rename)。"""
    ENDPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: Endpoint = {"url": url, "token": token, "pid": pid}
    _TMP_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(_TMP_PATH, ENDPOINT_PATH)


def delete_endpoint() -> None:
    """幂等删除;文件不存在不报错。"""
    with contextlib.suppress(FileNotFoundError):
        ENDPOINT_PATH.unlink()


def read_endpoint() -> Endpoint | None:
    """读 endpoint.json;文件不存在或格式坏返回 None。"""
    try:
        raw = ENDPOINT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    d = cast(dict[str, Any], data)
    if not all(k in d for k in ("url", "token", "pid")):
        return None
    return Endpoint(url=str(d["url"]), token=str(d["token"]), pid=int(d["pid"]))
