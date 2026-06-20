"""httpx 转发器 + SSE 流式透传 + 跨格式翻译接入(阶段 2.3-2.5)。

层次
----

1. `Forwarder.forward()`:dataplane 入口,接收客户端 server_api + body + upstream + 流/非流标志
2. 按 `upstream.native_api` 决定上游 API 类型;若与客户端 server_api 一致
   → 走 `_forward_passthrough_once` / `_forward_passthrough_stream` 原样转发
3. 否则走翻译路径:
   - 非流:`_forward_translated_once` → dispatcher.translate_request → 上游 → translate_response
   - 流:`_forward_translated_stream` → 上游 SSE → translate_stream_bytes → 客户端

`Forwarder` 实例由 app lifespan 管理(`open()` / `close()`),挂在 `app.state.forwarder`。
auth header 按 upstream.native_api 分:`messages` 用 `x-api-key`,其余走 `Authorization: Bearer`。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import httpx
from fastapi.responses import Response, StreamingResponse

from rosetta.server.database.models import Upstream
from rosetta.server.logs_config import SseTextCollector, request_text_for, response_text_for
from rosetta.server.service.exceptions import ServiceError
from rosetta.server.service.log_writer import log_writer
from rosetta.server.service.mock import mock_responder
from rosetta.server.translation.degradation import (
    StatefulNotTranslatableError,
    degrade_responses_request,
)
from rosetta.server.translation.dispatcher import (
    translate_request,
    translate_response,
    translate_stream_bytes,
)
from rosetta.shared.server_api import (
    DEFAULT_SERVER_API_PATHS,
    ServerApi,
)

_log = logging.getLogger("rosetta.server.forwarder")

# 超时:连接 10s、读取 5min(LLM 长响应常态)
_DEFAULT_TIMEOUT = httpx.Timeout(300.0, connect=10.0)


@dataclass
class UpstreamProbeResult:
    ok: bool
    upstream_id: str
    upstream_name: str
    native_api: str
    status_code: int | None
    category: str
    summary: str
    detail: str | None = None


@dataclass(frozen=True)
class _UsageSnapshot:
    input_tokens: int | None = None
    output_tokens: int | None = None


class Forwarder:
    """dataplane 转发器。封装 httpx client 生命周期与四条转发路径。

    生命周期由 app lifespan 驱动:`open()` 创建 httpx client,`close()` 关闭。
    测试场景可直接赋 `self._client = <mock>` 绕过 open,对应 test_dataplane.py 的 fixture。
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def open(self) -> None:
        # rosetta 自己管理 upstream base_url;不读取系统代理配置,避免内网 upstream
        # 被本机代理/网关误路由后返回空 502。
        self._client = httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, trust_env=False)

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
    def _auth_headers(upstream: Upstream, override_key: str | None = None) -> dict[str, str]:
        """按 `upstream.native_api` 选上游鉴权头写法;`override_key` 非空则覆盖 DB 的 `api_key`。

        客户端按入口协议带来的真实 API key 优先透传给上游(Claude 入口为 `x-api-key`,
        OpenAI-compatible 入口为 `Authorization: Bearer` 中的 token);客户端没带 key 时才
        fallback 到 `upstreams.api_key`。`r-api-key` 仅用于 Rosetta server-level 鉴权(暂不启用)。
        """
        key = override_key or upstream.api_key
        if key is None:
            raise ServiceError(
                status=500,
                code="upstream_missing_key",
                message=(
                    f"upstream '{upstream.name}' 没配 api_key,且客户端请求也未带对应鉴权头"
                ),
            )
        if upstream.native_api == "messages":
            return {
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            }
        return {"authorization": f"Bearer {key}"}

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

    async def probe_upstream(self, upstream: Upstream) -> UpstreamProbeResult:
        """最小探测 upstream 连通性与配置正确性,不写业务 logs。"""
        if upstream.provider == "mock":
            return UpstreamProbeResult(
                ok=True,
                upstream_id=upstream.id,
                upstream_name=upstream.name,
                native_api=upstream.native_api,
                status_code=200,
                category="ok",
                summary="mock upstream 响应正常",
            )
        if not upstream.model:
            return UpstreamProbeResult(
                ok=False,
                upstream_id=upstream.id,
                upstream_name=upstream.name,
                native_api=upstream.native_api,
                status_code=None,
                category="config",
                summary="缺少 model;先为该 upstream 配一个默认模型再测试",
            )

        native_api = ServerApi(upstream.native_api)
        url = self._base_url_for(upstream) + DEFAULT_SERVER_API_PATHS[native_api]
        body = json.dumps(self._probe_body(native_api, upstream.model), ensure_ascii=False).encode(
            "utf-8"
        )
        try:
            headers = {
                "content-type": "application/json",
                **self._auth_headers(upstream),
            }
            resp = await self._send_upstream(url, headers, body, stream=False)
        except ServiceError as e:
            category = "config" if e.code == "upstream_missing_key" else "network"
            return UpstreamProbeResult(
                ok=False,
                upstream_id=upstream.id,
                upstream_name=upstream.name,
                native_api=upstream.native_api,
                status_code=e.status,
                category=category,
                summary=e.message,
            )

        if resp.status_code >= 400:
            body_text = _response_text(resp)
            category, summary = self._classify_probe_failure(resp.status_code, body_text)
            return UpstreamProbeResult(
                ok=False,
                upstream_id=upstream.id,
                upstream_name=upstream.name,
                native_api=upstream.native_api,
                status_code=resp.status_code,
                category=category,
                summary=summary,
                detail=body_text or None,
            )

        try:
            payload = resp.json()
        except ValueError as e:
            return UpstreamProbeResult(
                ok=False,
                upstream_id=upstream.id,
                upstream_name=upstream.name,
                native_api=upstream.native_api,
                status_code=resp.status_code,
                category="invalid_response",
                summary=f"上游返回非 JSON 响应: {e}",
            )
        if not isinstance(payload, dict):
            return UpstreamProbeResult(
                ok=False,
                upstream_id=upstream.id,
                upstream_name=upstream.name,
                native_api=upstream.native_api,
                status_code=resp.status_code,
                category="invalid_response",
                summary="上游返回的 JSON 顶层不是对象",
            )
        return UpstreamProbeResult(
            ok=True,
            upstream_id=upstream.id,
            upstream_name=upstream.name,
            native_api=upstream.native_api,
            status_code=resp.status_code,
            category="ok",
            summary="request succeeded with configured api_key/model",
        )

    @staticmethod
    def _probe_body(native_api: ServerApi, model: str) -> dict[str, Any]:
        if native_api is ServerApi.MESSAGES:
            return {
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
            }
        if native_api is ServerApi.CHAT_COMPLETIONS:
            return {
                "model": model,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            }
        return {
            "model": model,
            "max_output_tokens": 1,
            "input": "ping",
        }

    @staticmethod
    def _classify_probe_failure(status_code: int, body_text: str) -> tuple[str, str]:
        lower = body_text.lower()
        if status_code in (401, 403):
            return ("auth", "authentication failed; check api_key")
        if "model" in lower and status_code in (400, 404, 422):
            return ("model", "model validation failed; check upstream.model")
        return ("upstream_error", f"upstream returned HTTP {status_code}")

    # ---------- 主入口 ----------

    async def forward(
        self,
        upstream: Upstream,
        server_api: ServerApi,
        body: bytes,
        content_type: str,
        api_type_paths: dict[str, str] | None = None,
        extra_response_headers: dict[str, str] | None = None,
        client_api_key: str | None = None,
        client_addr: str | None = None,
    ) -> Response:
        """把请求按格式翻译(必要时)+ 转发到上游。

        `extra_response_headers`:由上层(例如 degradation 层)传入的附加响应头,
        例:`{"r-warnings": "store_ignored,builtin_tools_removed:web_search"}`

        `client_api_key`:客户端按入口协议透传来的上游 key(Messages 为 x-api-key,
        OpenAI-compatible 为 Authorization Bearer token)。
        为 None 时 forwarder 用 `upstream.api_key`(DB 兜底)。见 DESIGN §8.1 / §8.5。

        埋点:每次调用在 `logs` 表留一条(status=ok/error + latency)。流式路径的
        latency 仅是"请求分发到响应构造"的时间,不含流持续时长;v1+ 再细化。
        """
        t0 = time.monotonic()
        model: str | None = None
        request_text: str | None = None
        try:
            body_dict = self._parse_body(body)
            request_text = request_text_for(server_api, body_dict)
            raw_model = body_dict.get("model")

            # model fallback:body 缺 / 空 model + upstream.model 有值 → 写入 body_dict
            # 同格式直通走原始 bytes,fallback 命中需要重新序列化
            needs_model_fallback = (
                not isinstance(raw_model, str) or not raw_model.strip()
            ) and upstream.model
            if needs_model_fallback:
                body_dict["model"] = upstream.model
                body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
                raw_model = upstream.model

            if isinstance(raw_model, str):
                model = raw_model
            is_stream = body_dict.get("stream") is True

            # provider=mock 短路:不发 HTTP,本地 echo 生成响应
            if upstream.provider == "mock":
                resp = await mock_responder.respond(server_api, body_dict, stream=is_stream)
            else:
                resp = await self._forward_upstream(
                    upstream=upstream,
                    server_api=server_api,
                    api_type_paths=api_type_paths,
                    body=body,
                    body_dict=body_dict,
                    is_stream=is_stream,
                    client_api_key=client_api_key,
                )
                # 跨格式降级可能产生 warnings 要塞回响应头
                warnings_header = getattr(resp, "_rosetta_warnings_header", None)
                if warnings_header:
                    extra_response_headers = dict(extra_response_headers or {})
                    extra_response_headers["r-warnings"] = warnings_header

            if isinstance(resp, StreamingResponse):
                resp = self._wrap_streaming_response_for_logging(
                    resp,
                    upstream=upstream,
                    server_api=server_api,
                    model=model,
                    t0=t0,
                    request_text=request_text,
                    client_addr=client_addr,
                )
            else:
                usage = self._response_usage_for_log(server_api, resp)
                await self._record_log(
                    upstream,
                    model,
                    "ok",
                    t0,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    client_addr=client_addr,
                    request_text=request_text,
                    response_text=self._response_text_for_log(server_api, resp),
                )
            return self._with_extra_headers(resp, extra_response_headers)
        except ServiceError as e:
            await self._record_log(
                upstream,
                model,
                "error",
                t0,
                error=f"{e.code}: {e.message}",
                client_addr=client_addr,
                request_text=request_text,
            )
            raise
        except Exception as e:  # pragma: no cover — 防御:service 层理论上不会漏
            await self._record_log(
                upstream,
                model,
                "error",
                t0,
                error=str(e),
                client_addr=client_addr,
                request_text=request_text,
            )
            raise

    async def _forward_upstream(
        self,
        *,
        upstream: Upstream,
        server_api: ServerApi,
        api_type_paths: dict[str, str] | None,
        body: bytes,
        body_dict: dict[str, Any],
        is_stream: bool,
        client_api_key: str | None,
    ) -> Response:
        """真实上游(非 mock)的转发路径:同格式直通 / 跨格式翻译二选一。"""
        native_api = ServerApi(upstream.native_api)
        paths = api_type_paths or DEFAULT_SERVER_API_PATHS
        api_type_path = paths.get(native_api.value)
        if not api_type_path:
            raise ServiceError(
                status=500,
                code="api_type_path_missing",
                message=f"api_types 缺少 native_api={native_api.value} 的 path",
            )
        url = self._base_url_for(upstream) + api_type_path
        headers = {
            "content-type": "application/json",
            **self._auth_headers(upstream, override_key=client_api_key),
        }

        _log.debug(
            "forward: source=%s target=%s stream=%s",
            server_api.value,
            native_api.value,
            is_stream,
        )

        # 同格式直通(阶段 1.3 路径)
        if native_api is server_api:
            if not is_stream:
                return await self._forward_passthrough_once(url, headers, body)
            return await self._forward_passthrough_stream(url, headers, body)

        # 跨格式翻译(阶段 2.3+):body_dict 已 parse,直接使用
        warnings_header = ""
        # Responses → 非 Responses:先降级(剥 stateful 阻断字段、store、内置 tools)
        if server_api is ServerApi.RESPONSES:
            try:
                degraded = degrade_responses_request(body_dict, target_api=native_api)
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
            warnings_header = degraded.warnings_header() or ""

        try:
            upstream_body = translate_request(body_dict, source=server_api, target=native_api)
        except ValueError as e:
            raise ServiceError(
                status=400,
                code="translation_failed",
                message=f"请求翻译失败({server_api.value} → {native_api.value}): {e}",
            ) from e

        upstream_bytes = json.dumps(upstream_body, ensure_ascii=False).encode("utf-8")

        if not is_stream:
            resp = await self._forward_translated_once(
                url,
                headers,
                upstream_bytes,
                native_api=native_api,
                server_api=server_api,
            )
        else:
            resp = await self._forward_translated_stream(
                url,
                headers,
                upstream_bytes,
                native_api=native_api,
                server_api=server_api,
            )
        if warnings_header:
            # 用临时属性捎带给外层 forward 拼 extra_response_headers;
            # 避免让 _forward_upstream 的返回类型变复杂
            resp._rosetta_warnings_header = warnings_header  # type: ignore[attr-defined]
        return resp

    async def _record_log(
        self,
        upstream: Upstream,
        model: str | None,
        status: str,
        t0: float,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
        client_addr: str | None = None,
        request_text: str | None = None,
        response_text: str | None = None,
    ) -> None:
        """写一条请求流水;LogWriter 内部已兜底,这里不用 try。"""
        latency_ms = int((time.monotonic() - t0) * 1000)
        # mock 上游不发 HTTP,upstream.base_url 是 'mock://'(seed 钉死);
        # 直接快照 base_url,显式标识就在数据里
        await log_writer.record(
            upstream_id=upstream.id,
            model=model,
            status=status,  # type: ignore[arg-type]
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            error=error,
            client_addr=client_addr,
            upstream_url=upstream.base_url,
            request_text=request_text,
            response_text=response_text,
        )

    def _response_text_for_log(self, server_api: ServerApi, resp: Response) -> str | None:
        body = getattr(resp, "body", b"")
        if not isinstance(body, (bytes, bytearray)) or not body:
            return None
        try:
            payload = json.loads(bytes(body))
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        return response_text_for(server_api, cast(dict[str, Any], payload))

    def _response_usage_for_log(self, server_api: ServerApi, resp: Response) -> _UsageSnapshot:
        body = getattr(resp, "body", b"")
        if not isinstance(body, (bytes, bytearray)) or not body:
            return _UsageSnapshot()
        try:
            payload = json.loads(bytes(body))
        except (TypeError, ValueError):
            return _UsageSnapshot()
        if not isinstance(payload, dict):
            return _UsageSnapshot()
        return _usage_snapshot_for(server_api, cast(dict[str, Any], payload))

    def _wrap_streaming_response_for_logging(
        self,
        resp: StreamingResponse,
        *,
        upstream: Upstream,
        server_api: ServerApi,
        model: str | None,
        t0: float,
        request_text: str | None,
        client_addr: str | None,
    ) -> StreamingResponse:
        collector = SseTextCollector(server_api)
        usage_collector = _SseUsageCollector(server_api)
        original_iter = resp.body_iterator

        async def _iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in original_iter:
                    data = self._stream_chunk_to_bytes(chunk)
                    collector.feed(data)
                    usage_collector.feed(data)
                    yield data
            finally:
                collector.finish()
                usage_collector.finish()
                await self._record_log(
                    upstream,
                    model,
                    "ok",
                    t0,
                    input_tokens=usage_collector.input_tokens,
                    output_tokens=usage_collector.output_tokens,
                    client_addr=client_addr,
                    request_text=request_text,
                    response_text=collector.text,
                )

        wrapped = StreamingResponse(
            _iter(),
            status_code=resp.status_code,
            media_type=resp.media_type,
            background=resp.background,
        )
        for key, value in resp.headers.items():
            wrapped.headers[key] = value
        return wrapped

    @staticmethod
    def _stream_chunk_to_bytes(chunk: object) -> bytes:
        if isinstance(chunk, bytes):
            return chunk
        if isinstance(chunk, str):
            return chunk.encode("utf-8")
        if isinstance(chunk, bytearray):
            return bytes(chunk)
        if isinstance(chunk, memoryview):
            return chunk.tobytes()
        raise TypeError(f"unsupported streaming chunk type: {type(chunk).__name__}")

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
        native_api: ServerApi,
        server_api: ServerApi,
    ) -> Response:
        resp = await self._send_upstream(url, headers, upstream_body, stream=False)
        if resp.status_code >= 400:
            # 上游错误原样返回(不翻译),但保留客户端 server_api 语义:状态码 + body 透传
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
                source=native_api,
                target=server_api,
            )
        except ValueError as e:
            raise ServiceError(
                status=502,
                code="translation_failed",
                message=f"响应翻译失败({native_api.value} → {server_api.value}): {e}",
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
        native_api: ServerApi,
        server_api: ServerApi,
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
                source=native_api,
                target=server_api,
            ):
                yield out

        return StreamingResponse(
            _iter_translated(),
            status_code=upstream.status_code,
            media_type="text/event-stream",
        )


# 模块级单例:app lifespan 负责 open/close;routes / 测试直接 import 使用
forwarder = Forwarder()


def _usage_snapshot_for(server_api: ServerApi, data: dict[str, Any]) -> _UsageSnapshot:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return _UsageSnapshot()
    u = cast(dict[str, Any], usage)
    if server_api is ServerApi.CHAT_COMPLETIONS:
        return _UsageSnapshot(
            input_tokens=int(u.get("prompt_tokens", 0) or 0),
            output_tokens=int(u.get("completion_tokens", 0) or 0),
        )
    return _UsageSnapshot(
        input_tokens=int(u.get("input_tokens", 0) or 0),
        output_tokens=int(u.get("output_tokens", 0) or 0),
    )


class _SseUsageCollector:
    def __init__(self, server_api: ServerApi) -> None:
        self.server_api = server_api
        self._buffer = b""
        self.input_tokens: int | None = None
        self.output_tokens: int | None = None

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk
        while True:
            sep_idx = -1
            sep_len = 0
            for sep in (b"\r\n\r\n", b"\n\n"):
                idx = self._buffer.find(sep)
                if idx != -1 and (sep_idx == -1 or idx < sep_idx):
                    sep_idx = idx
                    sep_len = len(sep)
            if sep_idx == -1:
                break
            frame = self._buffer[:sep_idx]
            self._buffer = self._buffer[sep_idx + sep_len :]
            self._consume_frame(frame)

    def finish(self) -> None:
        if self._buffer.strip():
            self._consume_frame(self._buffer)
        self._buffer = b""

    def _consume_frame(self, frame: bytes) -> None:
        parsed = _parse_sse_usage_frame(frame)
        if parsed is None:
            return
        event_name, data = parsed
        self._update_usage(event_name, data)

    def _update_usage(self, event_name: str | None, data: dict[str, Any]) -> None:
        if self.server_api is ServerApi.MESSAGES:
            etype = event_name or data.get("type")
            if etype == "message_start":
                message = data.get("message")
                if isinstance(message, dict):
                    usage = cast(dict[str, Any], message).get("usage")
                    if isinstance(usage, dict):
                        ud = cast(dict[str, Any], usage)
                        self.input_tokens = int(ud.get("input_tokens", 0) or 0)
                        self.output_tokens = int(ud.get("output_tokens", 0) or 0)
            elif etype == "message_delta":
                usage = data.get("usage")
                if isinstance(usage, dict):
                    ud = cast(dict[str, Any], usage)
                    output_tokens = ud.get("output_tokens")
                    if isinstance(output_tokens, int):
                        self.output_tokens = output_tokens
            return

        if self.server_api is ServerApi.CHAT_COMPLETIONS:
            usage = data.get("usage")
            if isinstance(usage, dict):
                ud = cast(dict[str, Any], usage)
                self.input_tokens = int(ud.get("prompt_tokens", 0) or 0)
                self.output_tokens = int(ud.get("completion_tokens", 0) or 0)
            return

        etype = event_name or data.get("type")
        if etype != "response.completed":
            return
        response = data.get("response")
        if not isinstance(response, dict):
            return
        usage = cast(dict[str, Any], response).get("usage")
        if not isinstance(usage, dict):
            return
        ud = cast(dict[str, Any], usage)
        self.input_tokens = int(ud.get("input_tokens", 0) or 0)
        self.output_tokens = int(ud.get("output_tokens", 0) or 0)


def _parse_sse_usage_frame(frame: bytes) -> tuple[str | None, dict[str, Any]] | None:
    event_name: str | None = None
    data_lines: list[str] = []
    for raw_line in frame.split(b"\n"):
        line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
    if not data_lines:
        return None
    payload = "\n".join(data_lines)
    if payload.strip() == "[DONE]":
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return event_name, cast(dict[str, Any], data)


def _response_text(resp: httpx.Response, limit: int = 400) -> str:
    try:
        text = resp.text
    except Exception:
        return ""
    return text[:limit]
