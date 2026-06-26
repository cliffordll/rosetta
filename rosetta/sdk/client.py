"""Rosetta SDK: HTTP admin / dataplane client."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, Literal, cast

import httpx

from rosetta.server.controller.chat import ChatConfigOut
from rosetta.server.controller.logs import LogListResponse, LogsClearOut, LogsConfigOut
from rosetta.server.controller.runtime import StatusResponse
from rosetta.server.controller.setup import SetupConfigOut, SetupTarget
from rosetta.server.controller.stats import Period, StatsOut
from rosetta.server.controller.upstreams import (
    ClientGuideOut,
    ModelOut,
    RestoreMockOut,
    UpstreamCreate,
    UpstreamOut,
    UpstreamProbeOut,
    UpstreamUpdate,
)
from rosetta.shared.server_api import ServerApi

_ADMIN_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
_STREAM_TIMEOUT = httpx.Timeout(600.0, connect=10.0)
ClientMode = Literal["server", "direct"]


class ProxyClient:
    def __init__(
        self,
        base_url: str,
        *,
        http: httpx.AsyncClient | None = None,
        mode: ClientMode = "server",
        _direct_api_key: str | None = None,
        direct_server_api: ServerApi | None = None,
        direct_model: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.AsyncClient(timeout=_ADMIN_TIMEOUT)
        self.mode = mode
        self._owns_http = http is None
        self._direct_api_key = _direct_api_key
        self.direct_server_api = direct_server_api
        self.direct_model = direct_model

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    def _require_server(self, method: str) -> None:
        if self.mode != "server":
            raise RuntimeError(f"direct 模式不支持 admin 操作: {method}")

    async def ping(self) -> bool:
        self._require_server("ping")
        try:
            resp = await self.http.get(f"{self.base_url}/admin/ping", timeout=_ADMIN_TIMEOUT)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    async def status(self) -> StatusResponse:
        self._require_server("status")
        resp = await self.http.get(f"{self.base_url}/admin/status", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return StatusResponse.model_validate(resp.json())

    async def shutdown(self) -> None:
        self._require_server("shutdown")
        resp = await self.http.post(f"{self.base_url}/admin/shutdown", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()

    async def list_upstreams(self) -> list[UpstreamOut]:
        self._require_server("list_upstreams")
        resp = await self.http.get(f"{self.base_url}/admin/upstreams", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise RuntimeError("GET /admin/upstreams 返回非 list")
        return [UpstreamOut.model_validate(item) for item in cast(list[object], items)]

    async def list_model_defaults(self) -> dict[str, str]:
        self._require_server("list_model_defaults")
        resp = await self.http.get(
            f"{self.base_url}/admin/upstreams/model-defaults",
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        data = cast(dict[str, Any], resp.json())
        return {str(k): str(v) for k, v in data.items()}

    async def list_models(self) -> list[ModelOut]:
        self._require_server("list_models")
        resp = await self.http.get(f"{self.base_url}/admin/models", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            raise RuntimeError("GET /admin/models 返回非 list")
        return [ModelOut.model_validate(item) for item in cast(list[object], items)]

    async def set_model_alias(self, model_name: str, alias: str | None) -> ModelOut:
        self._require_server("set_model_alias")
        resp = await self.http.put(
            f"{self.base_url}/admin/models/{model_name}/alias",
            json={"alias": alias},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return ModelOut.model_validate(resp.json())

    async def set_model_enabled(self, model_name: str, enabled: bool) -> ModelOut:
        self._require_server("set_model_enabled")
        resp = await self.http.put(
            f"{self.base_url}/admin/models/{model_name}/enabled",
            json={"enabled": enabled},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return ModelOut.model_validate(resp.json())

    async def test_upstream(self, upstream_id: str) -> UpstreamProbeOut:
        self._require_server("test_upstream")
        resp = await self.http.post(
            f"{self.base_url}/admin/upstreams/{upstream_id}/test",
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return UpstreamProbeOut.model_validate(resp.json())

    async def create_upstream(self, payload: UpstreamCreate) -> UpstreamOut:
        self._require_server("create_upstream")
        resp = await self.http.post(
            f"{self.base_url}/admin/upstreams",
            json=payload.model_dump(mode="json"),
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return UpstreamOut.model_validate(resp.json())

    async def delete_upstream(self, upstream_id: str) -> None:
        self._require_server("delete_upstream")
        resp = await self.http.delete(
            f"{self.base_url}/admin/upstreams/{upstream_id}",
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()

    async def update_upstream(
        self,
        upstream_id: str,
        payload: UpstreamUpdate | None = None,
        **fields: Any,
    ) -> UpstreamOut:
        self._require_server("update_upstream")
        body = payload.model_dump(exclude_unset=True, mode="json") if payload else fields
        resp = await self.http.put(
            f"{self.base_url}/admin/upstreams/{upstream_id}",
            json={k: v for k, v in body.items() if v is not None},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return UpstreamOut.model_validate(resp.json())

    async def set_model_default_upstream(self, upstream_id: str, *, model: str) -> UpstreamOut:
        self._require_server("set_model_default_upstream")
        resp = await self.http.put(
            f"{self.base_url}/admin/upstreams/{upstream_id}/model-default",
            params={"model": model},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return UpstreamOut.model_validate(resp.json())

    async def restore_mock_upstream(self, *, force: bool = False) -> RestoreMockOut:
        self._require_server("restore_mock_upstream")
        resp = await self.http.post(
            f"{self.base_url}/admin/upstreams/restore-mock",
            params={"force": "true" if force else "false"},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return RestoreMockOut.model_validate(resp.json())

    async def get_client_guide(self, client: str) -> ClientGuideOut:
        self._require_server("get_client_guide")
        resp = await self.http.get(
            f"{self.base_url}/admin/upstreams/guide/{client}",
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return ClientGuideOut.model_validate(resp.json())

    async def list_logs(self, **params: Any) -> LogListResponse:
        self._require_server("list_logs")
        resp = await self.http.get(
            f"{self.base_url}/admin/logs",
            params={k: v for k, v in params.items() if v is not None},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return LogListResponse.model_validate(resp.json())

    async def logs_config(self) -> LogsConfigOut:
        self._require_server("logs_config")
        resp = await self.http.get(f"{self.base_url}/admin/logs/config", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return LogsConfigOut.model_validate(resp.json())

    async def update_logs_config(
        self, *, log_content: str | None = None, page_size: int | None = None
    ) -> LogsConfigOut:
        self._require_server("update_logs_config")
        resp = await self.http.put(
            f"{self.base_url}/admin/logs/config",
            json={
                k: v
                for k, v in {"log_content": log_content, "page_size": page_size}.items()
                if v is not None
            },
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return LogsConfigOut.model_validate(resp.json())

    async def clear_logs(self) -> int:
        self._require_server("clear_logs")
        resp = await self.http.delete(f"{self.base_url}/admin/logs", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return LogsClearOut.model_validate(resp.json()).deleted

    async def stats(self, period: Period | None = None) -> StatsOut:
        self._require_server("stats")
        params = {"period": period} if period else {}
        resp = await self.http.get(
            f"{self.base_url}/admin/stats",
            params=params,
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return StatsOut.model_validate(resp.json())

    async def get_stats(self, period: Period | None = None) -> StatsOut:
        return await self.stats(period)

    async def chat_config(self) -> ChatConfigOut:
        self._require_server("chat_config")
        resp = await self.http.get(f"{self.base_url}/admin/chat/config", timeout=_ADMIN_TIMEOUT)
        resp.raise_for_status()
        return ChatConfigOut.model_validate(resp.json())

    async def update_chat_config(
        self, *, max_tokens: int | None = None, stream: bool | None = None
    ) -> ChatConfigOut:
        self._require_server("update_chat_config")
        resp = await self.http.put(
            f"{self.base_url}/admin/chat/config",
            json={
                k: v
                for k, v in {"max_tokens": max_tokens, "stream": stream}.items()
                if v is not None
            },
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return ChatConfigOut.model_validate(resp.json())

    async def setup_preview(self, target: SetupTarget, *, model: str) -> SetupConfigOut:
        self._require_server("setup_preview")
        resp = await self.http.get(
            f"{self.base_url}/admin/setup/{target}/preview",
            params={"model": model},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return SetupConfigOut.model_validate(resp.json())

    async def setup_apply(self, target: SetupTarget, *, model: str) -> SetupConfigOut:
        self._require_server("setup_apply")
        resp = await self.http.post(
            f"{self.base_url}/admin/setup/{target}/apply",
            json={"model": model},
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return SetupConfigOut.model_validate(resp.json())

    async def setup_clear(self, target: SetupTarget) -> SetupConfigOut:
        self._require_server("setup_clear")
        resp = await self.http.post(
            f"{self.base_url}/admin/setup/{target}/clear",
            timeout=_ADMIN_TIMEOUT,
        )
        resp.raise_for_status()
        return SetupConfigOut.model_validate(resp.json())

    def data_url_and_headers(
        self,
        server_api: ServerApi,
        *,
        override_api_key: str | None = None,
        upstream_header: str | None = None,
    ) -> tuple[str, dict[str, str]]:
        headers: dict[str, str] = {"content-type": "application/json"}
        if self.mode == "server" and upstream_header:
            headers["r-upstream"] = upstream_header
        key = override_api_key or self._direct_api_key
        if key:
            if server_api is ServerApi.MESSAGES:
                headers["x-api-key"] = key
            else:
                headers["authorization"] = f"Bearer {key}"
        return (self._data_url(server_api), headers)

    async def post_chat(
        self,
        server_api: ServerApi,
        body: dict[str, Any],
        *,
        override_api_key: str | None = None,
        upstream_header: str | None = None,
    ) -> httpx.Response:
        url, headers = self.data_url_and_headers(
            server_api,
            override_api_key=override_api_key,
            upstream_header=upstream_header,
        )
        return await self.http.post(url, json=body, headers=headers, timeout=_STREAM_TIMEOUT)

    @asynccontextmanager
    async def stream_chat(
        self,
        server_api: ServerApi,
        body: dict[str, Any],
        *,
        override_api_key: str | None = None,
        upstream_header: str | None = None,
    ) -> AsyncGenerator[httpx.Response]:
        url, headers = self.data_url_and_headers(
            server_api,
            override_api_key=override_api_key,
            upstream_header=upstream_header,
        )
        async with self.http.stream(
            "POST",
            url,
            json=body,
            headers=headers,
            timeout=_STREAM_TIMEOUT,
        ) as resp:
            yield resp

    def _data_url(self, server_api: ServerApi) -> str:
        path_map = {
            ServerApi.MESSAGES: "/v1/messages",
            ServerApi.CHAT_COMPLETIONS: "/v1/chat/completions",
            ServerApi.RESPONSES: "/v1/responses",
        }
        return f"{self.base_url}{path_map[server_api]}"

    @staticmethod
    def force_stop() -> None:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/f", "/im", "rosetta.exe"], capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "rosetta"], capture_output=True)

    @staticmethod
    @asynccontextmanager
    async def direct_session(
        *,
        base_url: str,
        api_key: str,
        server_api: ServerApi,
        model: str,
    ) -> AsyncGenerator[ProxyClient]:
        client = ProxyClient(
            base_url,
            mode="direct",
            _direct_api_key=api_key,
            direct_server_api=server_api,
            direct_model=model,
        )
        try:
            yield client
        finally:
            await client.close()

    @staticmethod
    @asynccontextmanager
    async def discover_session(
        *,
        spawn_if_missing: bool = True,
        port: int = 1687,
        wait_seconds: int = 10,
    ) -> AsyncGenerator[ProxyClient]:
        if not _port_open(port):
            if not spawn_if_missing:
                raise RuntimeError(f"port {port} 上没有 Rosetta server")
            _spawn(port)
            _wait_for_port(port, wait_seconds=wait_seconds)

        client = ProxyClient(f"http://127.0.0.1:{port}", mode="server")
        try:
            yield client
        finally:
            await client.close()


def _port_open(port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _spawn(port: int) -> None:
    subprocess.Popen(
        [sys.executable, "-m", "rosetta.cli", "start", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for_port(port: int, *, wait_seconds: int) -> None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _port_open(port):
            return
        time.sleep(0.3)
    raise RuntimeError(f"Rosetta server 未在 {wait_seconds}s 内启动")
