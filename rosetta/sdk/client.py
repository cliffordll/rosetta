"""`ProxyClient` — SDK 主入口:封装 `/admin/*` 调用 + 数据面 POST(流/非流)。

两种工厂
--------

- `ProxyClient.discover()`:async context manager;内部走 `discover()`,找到或启动
  本地 rosetta-server,构 httpx client 指向 server。admin 方法可用。
- `ProxyClient.direct()`:async context manager;绕过 server,httpx client 直连上游
  (DESIGN §8.6)。admin 方法不可用(raise);只能调 `send_chat()`。

Pydantic 模型复用
----------------
admin 相关的 request / response schema 直接从 `rosetta.server.admin.*` import
(DESIGN §9 单包结构允许);不在 SDK 这边手写第二份。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Self

import httpx

from rosetta.sdk.discover import discover
from rosetta.server.admin.health import StatusResponse
from rosetta.server.admin.logs import LogOut
from rosetta.server.admin.providers import ProviderCreate, ProviderOut
from rosetta.server.admin.routes import RouteIn, RouteOut
from rosetta.server.admin.stats import Period, StatsOut
from rosetta.shared.formats import UPSTREAM_PATH, Format

_DATA_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
_ADMIN_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass
class ProxyClient:
    """rosetta SDK 的 HTTP 客户端;admin + data plane 合二为一。"""

    http: httpx.AsyncClient
    base_url: str
    mode: Literal["server", "direct"] = "server"
    token: str | None = None

    # direct 模式专属:
    _direct_api_key: str | None = field(default=None, repr=False)
    _direct_format: Format | None = None
    _direct_model: str | None = None

    @classmethod
    @asynccontextmanager
    async def discover_session(
        cls, *, parent_pid: int | None = None, spawn_if_missing: bool = True
    ) -> AsyncIterator[Self]:
        """发现或拉起本地 server,返回连到它的 client。"""
        ep = await discover(parent_pid=parent_pid, spawn_if_missing=spawn_if_missing)
        http = httpx.AsyncClient(timeout=_DATA_TIMEOUT)
        try:
            yield cls(http=http, base_url=ep["url"], mode="server", token=ep["token"])
        finally:
            await http.aclose()

    @classmethod
    @asynccontextmanager
    async def direct_session(
        cls,
        *,
        base_url: str,
        api_key: str,
        format: Format,
        model: str,
    ) -> AsyncIterator[Self]:
        """direct 模式(DESIGN §8.6):绕 server 直连上游。"""
        http = httpx.AsyncClient(timeout=_DATA_TIMEOUT)
        try:
            yield cls(
                http=http,
                base_url=base_url.rstrip("/"),
                mode="direct",
                _direct_api_key=api_key,
                _direct_format=format,
                _direct_model=model,
            )
        finally:
            await http.aclose()

    # ---------- admin(server 模式独占)----------

    def _require_server(self, op: str) -> None:
        if self.mode != "server":
            raise RuntimeError(f"direct 模式不支持 admin 操作: {op}")

    async def ping(self) -> bool:
        self._require_server("ping")
        resp = await self.http.get(f"{self.base_url}/admin/ping", timeout=_ADMIN_TIMEOUT)
        return resp.status_code == 200

    async def status(self) -> StatusResponse:
        self._require_server("status")
        resp = await self.http.get(f"{self.base_url}/admin/status", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return StatusResponse.model_validate(resp.json())

    async def list_providers(self) -> list[ProviderOut]:
        self._require_server("list_providers")
        resp = await self.http.get(f"{self.base_url}/admin/providers", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise RuntimeError("GET /admin/providers 返回非 list")
        return [ProviderOut.model_validate(item) for item in items]  # pyright: ignore[reportUnknownVariableType]

    async def create_provider(self, payload: ProviderCreate) -> ProviderOut:
        self._require_server("create_provider")
        resp = await self.http.post(
            f"{self.base_url}/admin/providers",
            json=payload.model_dump(),
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return ProviderOut.model_validate(resp.json())

    async def delete_provider(self, provider_id: int) -> None:
        """删 provider;server 级联删引用它的 route。"""
        self._require_server("delete_provider")
        resp = await self.http.delete(
            f"{self.base_url}/admin/providers/{provider_id}",
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()

    async def list_routes(self) -> list[RouteOut]:
        self._require_server("list_routes")
        resp = await self.http.get(f"{self.base_url}/admin/routes", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise RuntimeError("GET /admin/routes 返回非 list")
        return [RouteOut.model_validate(item) for item in items]  # pyright: ignore[reportUnknownVariableType]

    async def replace_routes(self, payload: list[RouteIn]) -> list[RouteOut]:
        self._require_server("replace_routes")
        resp = await self.http.put(
            f"{self.base_url}/admin/routes",
            json=[r.model_dump() for r in payload],
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise RuntimeError("PUT /admin/routes 返回非 list")
        return [RouteOut.model_validate(item) for item in items]  # pyright: ignore[reportUnknownVariableType]

    async def list_logs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        provider: str | None = None,
    ) -> list[LogOut]:
        self._require_server("list_logs")
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if provider:
            params["provider"] = provider
        resp = await self.http.get(
            f"{self.base_url}/admin/logs", params=params, timeout=_ADMIN_TIMEOUT
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise RuntimeError("GET /admin/logs 返回非 list")
        return [LogOut.model_validate(item) for item in items]  # pyright: ignore[reportUnknownVariableType]

    async def stats(self, *, period: Period = "today") -> StatsOut:
        self._require_server("stats")
        resp = await self.http.get(
            f"{self.base_url}/admin/stats",
            params={"period": period},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return StatsOut.model_validate(resp.json())

    async def shutdown(self) -> None:
        """请求 server 优雅关闭;response 返回后不等待实际退出。"""
        self._require_server("shutdown")
        resp = await self.http.post(f"{self.base_url}/admin/shutdown", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()

    # ---------- data plane ----------

    def _data_url_and_headers(
        self,
        fmt: Format,
        *,
        override_api_key: str | None,
        provider_header: str | None,
    ) -> tuple[str, dict[str, str]]:
        """按 mode 拼数据面 URL + header。"""
        path = UPSTREAM_PATH[fmt]
        if self.mode == "server":
            url = f"{self.base_url}{path}"
            headers: dict[str, str] = {"content-type": "application/json"}
            if override_api_key:
                headers["x-api-key"] = override_api_key
            if provider_header:
                headers["x-rosetta-provider"] = provider_header
            return url, headers

        # direct:自填上游鉴权 header
        if self._direct_api_key is None:
            raise RuntimeError("direct 模式未设置 api_key")
        if provider_header:
            raise RuntimeError("direct 模式不支持 provider_header(DESIGN §8.6 互斥)")
        url = f"{self.base_url}{path}"
        headers = {"content-type": "application/json"}
        if fmt is Format.MESSAGES:
            headers["x-api-key"] = self._direct_api_key
            headers["anthropic-version"] = "2023-06-01"
        else:
            headers["authorization"] = f"Bearer {self._direct_api_key}"
        return url, headers

    async def post_chat(
        self,
        fmt: Format,
        body: dict[str, Any],
        *,
        override_api_key: str | None = None,
        provider_header: str | None = None,
    ) -> httpx.Response:
        """非流式数据面 POST;调用方拿到 Response 自己 `.json()`。"""
        url, headers = self._data_url_and_headers(
            fmt, override_api_key=override_api_key, provider_header=provider_header
        )
        return await self.http.post(url, json=body, headers=headers)

    @asynccontextmanager
    async def stream_chat(
        self,
        fmt: Format,
        body: dict[str, Any],
        *,
        override_api_key: str | None = None,
        provider_header: str | None = None,
    ) -> AsyncIterator[httpx.Response]:
        """流式数据面 POST;返回 async context,`resp.aiter_bytes()` 读流。"""
        url, headers = self._data_url_and_headers(
            fmt, override_api_key=override_api_key, provider_header=provider_header
        )
        req = self.http.build_request("POST", url, json=body, headers=headers)
        resp = await self.http.send(req, stream=True)
        try:
            yield resp
        finally:
            await resp.aclose()

    @property
    def direct_format(self) -> Format | None:
        return self._direct_format

    @property
    def direct_model(self) -> str | None:
        return self._direct_model
