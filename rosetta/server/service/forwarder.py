"""httpx 转发器 + SSE 流式透传 + 跨格式翻译接入(阶段 2.3-2.5)。

层次
----

1. `Forwarder.forward()`:dataplane 入口,接收客户端 format + body + upstream + 流/非流标志
2. 按 `upstream.protocol` 决定上游 format;若与客户端 format 一致 → 走 `_forward_passthrough_once`
   / `_forward_passthrough_stream` 原样转发(兼容 1.3 路径,性能最优)
3. 否则走翻译路径:
   - 非流:`_forward_translated_once` → dispatcher.translate_request → 上游 → translate_response
   - 流:`_forward_translated_stream` → 上游 SSE → translate_stream_bytes → 客户端

`Forwarder` 实例由 app lifespan 管理(`open()` / `close()`),挂在 `app.state.forwarder`。
auth header 按 upstream.protocol 分:`messages` 用 `x-api-key`,其余走 `Authorization: Bearer`。
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx
from fastapi.responses import Response, StreamingResponse

from rosetta.server.database.models import Upstream
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.translation.degradation import (
    StatefulNotTranslatableError,
    degrade_responses_request,
)
from rosetta.server.translation.dispatcher import (
    translate_request,
    translate_response,
    translate_stream_bytes,
)
from rosetta.shared.protocols import (
    UPSTREAM_PATH,
    Protocol,
)

# 超时:连接 10s、读取 5min(LLM 长响应常态)
_DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


class Forwarder:
    """dataplane 转发器。封装 httpx client 生命周期与四条转发路径。

    生命周期由 app lifespan 驱动:`open()` 创建 httpx client,`close()` 关闭。
    测试场景可直接赋 `self._client = <mock>` 绕过 open,对应 test_dataplane.py 的 fixture。
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def open(self) -> None:
        self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("httpx client 未初始化,先调 Forwarder.open()")
        return self._client

    # ---------- 无状态 helper(上游配置、响应装配、流控) ----------

    @staticmethod
    def _base_url_for(upstream: Upstream) -> str:
        # base_url 在 DB 层已经 NOT NULL,直接 rstrip
        return upstream.base_url.rstrip("/")

    @staticmethod
    def _auth_headers(
        upstream: Upstream, override_key: str | None = None
    ) -> dict[str, str]:
        """按 `upstream.protocol` 选上游鉴权头写法;`override_key` 非空则覆盖 DB 的 `api_key`。

        DESIGN §8.1 约定:客户端请求若带 `x-api-key` / `Authorization: Bearer`,
        server 把这把 key 透传给上游(**不做** rosetta-level 的鉴权),不带才 fallback
        到 `upstreams.api_key`。override 机制让"临时换一把 key 试试"不需要改 DB。
        """
        key = override_key or upstream.api_key
        if key is None:
            raise ServiceError(
                status=500,
                code="upstream_missing_key",
                message=(
                    f"upstream '{upstream.name}' 没配 api_key,"
                    "且客户端请求也未带 x-api-key / Authorization 头"
                ),
            )
        if upstream.protocol == "messages":
            return {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            }
        return {"authorization": f"Bearer {key}"}

    @staticmethod
    def _debug_log_upstream_key(headers: dict[str, str]) -> None:
        """TODO(阶段 3.2 验证通过后删):打印发给上游的 key 前 10 字符。

        用途:人肉验证"客户端带 key → 透传 / 不带 → DB fallback"两条分支的实际走向。
        本函数写到 stderr 而非 logger,等阶段 4 logger 落地后再决定是否保留到 debug 级别。
        """
        key = headers.get("x-api-key")
        if not key:
            auth = headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                key = auth[7:].strip()
        if key:
            print(f"[rosetta.debug] upstream key prefix = {key[:10]}...", file=sys.stderr)

    @staticmethod
    def _with_extra_headers(resp: Response, extra: dict[str, str] | None) -> Response:
        if extra:
            for k, v in extra.items():
                resp.headers[k] = v
        return resp

    @staticmethod
    async def _passthrough_error(upstream: httpx.Response) -> Response:
        """流式路径下上游 ≥400:读完 body、关闭 upstream、原样返回给客户端。"""
        content = await upstream.aread()
        await upstream.aclose()
        return Response(
            content=content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    @staticmethod
    async def _iter_and_close(upstream: httpx.Response) -> AsyncIterator[bytes]:
        """统一的上游流生成器:透传原始字节,finally 保证 aclose。"""
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()

    @staticmethod
    def _parse_body(body: bytes) -> dict[str, Any]:
        """解析请求体为 dict;非法 JSON / 非 dict 顶层都直接 400。

        同格式直通 + 跨格式翻译共用。非 dict body 在 LLM API 下 100% 被上游拒,
        rosetta 提前 400 只是**更快**,不改变最终结果;客户端按 `error.type == "rosetta_error"`
        识别即可。
        """
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ServiceError(
                status=400,
                code="invalid_json_body",
                message=f"请求体不是合法 JSON: {e}",
            ) from e
        if not isinstance(data, dict):
            raise ServiceError(
                status=400,
                code="invalid_json_body",
                message="请求体 JSON 顶层必须是对象",
            )
        return cast(dict[str, Any], data)

    # ---------- 主入口 ----------

    async def forward(
        self,
        upstream: Upstream,
        request_protocol: Protocol,
        body: bytes,
        content_type: str,
        extra_response_headers: dict[str, str] | None = None,
        client_api_key: str | None = None,
    ) -> Response:
        """把请求按格式翻译(必要时)+ 转发到上游。

        `extra_response_headers`:由上层(例如 degradation 层)传入的附加响应头,
        例:`{"x-rosetta-warnings": "store_ignored,builtin_tools_removed:web_search"}`

        `client_api_key`:客户端通过 `x-api-key` / `Authorization: Bearer` 透传来的上游 key。
        为 None 时 forwarder 用 `upstream.api_key`(DB 兜底)。见 DESIGN §8.1 / §8.5。
        """
        body_dict = self._parse_body(body)
        is_stream = body_dict.get("stream") is True
        upstream_protocol = Protocol(upstream.protocol)
        url = self._base_url_for(upstream) + UPSTREAM_PATH[upstream_protocol]
        headers = {
            "content-type": "application/json",
            **self._auth_headers(upstream, override_key=client_api_key),
        }
        self._debug_log_upstream_key(headers)

        print(
            f"Resolved target format: {upstream_protocol.value}  "
            f"source format: {request_protocol.value}",
            flush=True,
        )
        # 同格式直通(阶段 1.3 路径)
        if upstream_protocol is request_protocol:
            if not is_stream:
                resp = await self._forward_passthrough_once(url, headers, body)
            else:
                resp = await self._forward_passthrough_stream(url, headers, body)
            return self._with_extra_headers(resp, extra_response_headers)

        # 跨格式翻译(阶段 2.3+):body_dict 已 parse,直接使用
        print(f"Request body: {json.dumps(body_dict)}", flush=True)

        # Responses → 非 Responses:先降级(剥 stateful 阻断字段、store、内置 tools)
        if request_protocol is Protocol.RESPONSES:
            try:
                degraded = degrade_responses_request(body_dict, target_protocol=upstream_protocol)
            except StatefulNotTranslatableError as e:
                raise ServiceError(
                    status=400,
                    code="stateful_not_translatable",
                    message=str(e),
                    field=e.field_name,
                ) from e
            except ValueError as e:
                raise ServiceError(
                    status=400,
                    code="responses_degradation_failed",
                    message=f"Responses 请求降级失败: {e}",
                ) from e
            body_dict = degraded.body
            warnings_header = degraded.warnings_header()
            if warnings_header:
                extra_response_headers = dict(extra_response_headers or {})
                extra_response_headers["x-rosetta-warnings"] = warnings_header

        try:
            upstream_body = translate_request(
                body_dict, source=request_protocol, target=upstream_protocol
            )
        except ValueError as e:
            raise ServiceError(
                status=400,
                code="translation_failed",
                message=f"请求翻译失败({request_protocol.value} → {upstream_protocol.value}): {e}",
            ) from e

        upstream_bytes = json.dumps(upstream_body, ensure_ascii=False).encode("utf-8")

        if not is_stream:
            resp = await self._forward_translated_once(
                url,
                headers,
                upstream_bytes,
                upstream_protocol=upstream_protocol,
                client_protocol=request_protocol,
            )
        else:
            resp = await self._forward_translated_stream(
                url,
                headers,
                upstream_bytes,
                upstream_protocol=upstream_protocol,
                client_protocol=request_protocol,
            )
        return self._with_extra_headers(resp, extra_response_headers)

    # ---------- 上游 IO helper ----------

    async def _send_upstream(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
        *,
        stream: bool,
    ) -> httpx.Response:
        """统一的上游 POST:`stream=False` 一次读完;`stream=True` 返回 open stream。

        httpx.RequestError 统一映射到 502。调用方负责在流式路径上关闭 upstream。
        """
        client = self._get_client()
        try:
            if stream:
                req = client.build_request("POST", url, headers=headers, content=body)
                return await client.send(req, stream=True)
            return await client.post(url, headers=headers, content=body)
        except httpx.RequestError as e:
            raise ServiceError(
                status=502,
                code="upstream_unreachable",
                message=f"上游不可达:{type(e).__name__}: {e}",
            ) from e

    # ---------- 同格式直通 ----------

    async def _forward_passthrough_once(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
    ) -> Response:
        resp = await self._send_upstream(url, headers, body, stream=False)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type", "application/json"),
        )

    async def _forward_passthrough_stream(
        self,
        url: str,
        headers: dict[str, str],
        body: bytes,
    ) -> Response:
        upstream = await self._send_upstream(url, headers, body, stream=True)
        if upstream.status_code >= 400:
            return await self._passthrough_error(upstream)
        return StreamingResponse(
            self._iter_and_close(upstream),
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "text/event-stream"),
        )

    # ---------- 跨格式翻译 ----------

    async def _forward_translated_once(
        self,
        url: str,
        headers: dict[str, str],
        upstream_body: bytes,
        *,
        upstream_protocol: Protocol,
        client_protocol: Protocol,
    ) -> Response:
        resp = await self._send_upstream(url, headers, upstream_body, stream=False)
        if resp.status_code >= 400:
            # 上游错误原样返回(不翻译),但保留客户端 format 语义:状态码 + body 透传
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
            )

        try:
            upstream_json: Any = resp.json()
        except ValueError as e:
            raise ServiceError(
                status=502,
                code="upstream_invalid_response",
                message=f"上游响应非 JSON: {e}",
            ) from e
        if not isinstance(upstream_json, dict):
            raise ServiceError(
                status=502,
                code="upstream_invalid_response",
                message="上游响应 JSON 顶层必须是对象",
            )

        try:
            client_body = translate_response(
                cast(dict[str, Any], upstream_json),
                source=upstream_protocol,
                target=client_protocol,
            )
        except ValueError as e:
            raise ServiceError(
                status=502,
                code="translation_failed",
                message=f"响应翻译失败({upstream_protocol.value} → {client_protocol.value}): {e}",
            ) from e

        return Response(
            content=json.dumps(client_body, ensure_ascii=False).encode("utf-8"),
            status_code=resp.status_code,
            media_type="application/json",
        )

    async def _forward_translated_stream(
        self,
        url: str,
        headers: dict[str, str],
        upstream_body: bytes,
        *,
        upstream_protocol: Protocol,
        client_protocol: Protocol,
    ) -> Response:
        """流式翻译:上游 SSE → `translate_stream_bytes` → 客户端 SSE。

        错误传播(DESIGN §8.3):
        - 上游非 2xx(未进入流)→ 原样透传错误响应
        - 上游 2xx 但流中抛异常 → 生成器 raise,StreamingResponse 关闭连接
          (不向客户端伪造额外事件)
        """
        upstream = await self._send_upstream(url, headers, upstream_body, stream=True)
        if upstream.status_code >= 400:
            return await self._passthrough_error(upstream)

        async def _iter_translated() -> AsyncIterator[bytes]:
            async for out in translate_stream_bytes(
                self._iter_and_close(upstream),
                source=upstream_protocol,
                target=client_protocol,
            ):
                yield out

        return StreamingResponse(
            _iter_translated(),
            status_code=upstream.status_code,
            media_type="text/event-stream",
        )


# 模块级单例:app lifespan 负责 open/close;routes / 测试直接 import 使用
forwarder = Forwarder()
