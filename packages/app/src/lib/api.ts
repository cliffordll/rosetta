/**
 * rosetta server admin API 薄封装。
 *
 * - 浏览器 / vite dev:相对路径 `/admin/*` + vite.config proxy 转到 server
 * - Tauri 壳内:webview origin 是 `https://tauri.localhost`,与 server 的
 *   `http://127.0.0.1:<port>` 跨 origin → 启动时 invoke `get_server_url`
 *   拿 base URL,之后所有 fetch 都 prepend
 * - 类型手写,对齐 `rosetta/server/controller/*.py` 的 Pydantic schema
 */

import { invoke } from "@tauri-apps/api/core";

/** server_api;与后端格式枚举的 str 值严格一致。 */
export const ServerApi = {
  MESSAGES: "messages",
  CHAT_COMPLETIONS: "completions",
  RESPONSES: "responses",
} as const;
export type ServerApi = (typeof ServerApi)[keyof typeof ServerApi];

export type UpstreamNativeApi = ServerApi;

export const SERVER_API_PATHS: Record<ServerApi, string> = {
  [ServerApi.MESSAGES]: "/v1/messages",
  [ServerApi.CHAT_COMPLETIONS]: "/v1/chat/completions",
  [ServerApi.RESPONSES]: "/v1/responses",
};

export function serverApiLabel(value: string): string {
  const path = SERVER_API_PATHS[value as ServerApi];
  return path ? `${value} (${path})` : value;
}

/** 厂商标识(对齐 `rosetta.server.database.models.UpstreamProvider`)。
 *  `MOCK` 是内置假上游,由 server 端 seed 在 DB 里;不出现在 Add 下拉,
 *  但 Upstreams 列表展示时需要识别此值。 */
export const UpstreamProvider = {
  ANTHROPIC: "anthropic",
  OPENAI: "openai",
  OPENROUTER: "openrouter",
  GOOGLE: "google",
  OLLAMA: "ollama",
  VLLM: "vllm",
  CUSTOM: "custom",
  MOCK: "mock",
} as const;
export type UpstreamProvider = (typeof UpstreamProvider)[keyof typeof UpstreamProvider];

/** Add 对话框下拉候选;不含 MOCK(由 server seed,不鼓励用户手动建)。 */
export const UPSTREAM_PROVIDERS: UpstreamProvider[] = [
  UpstreamProvider.ANTHROPIC,
  UpstreamProvider.OPENAI,
  UpstreamProvider.OPENROUTER,
  UpstreamProvider.GOOGLE,
  UpstreamProvider.OLLAMA,
  UpstreamProvider.VLLM,
  UpstreamProvider.CUSTOM,
];

export interface StatusResponse {
  version: string;
  uptime_ms: number;
  upstreams_count: number;
  /** 客户端抵达 server 的 base URL(含 scheme + host + port)。 */
  url: string;
}

export interface UpstreamOut {
  id: string;
  name: string;
  native_api: string;
  provider: string;
  base_url: string;
  /** 管理面回显 api_key,便于本地测试;生产/共享环境注意不要截图或外传。 */
  api_key: string | null;
  /** 该 upstream 的默认模型;client body 不传 model 时 server fallback 用这个。可空。 */
  model: string | null;
  enabled: boolean;
  created_at: string;
}

export type ModelDefaultsOut = Record<string, string>;

export interface UpstreamProbeOut {
  ok: boolean;
  upstream_id: string;
  upstream_name: string;
  native_api: string;
  status_code: number | null;
  category: string;
  summary: string;
  detail: string | null;
}

export interface UpstreamCreate {
  name: string;
  native_api: UpstreamNativeApi;
  provider: UpstreamProvider;
  api_key?: string;
  model?: string;
  base_url: string;
  enabled?: boolean;
}

/** PUT /admin/upstreams/{id} body;只发显式 set 的字段。
 *
 * - `api_key` / `model` 显式 `null` → 清空该字段;未传 → 不动
 */
export interface UpstreamUpdate {
  name?: string;
  native_api?: UpstreamNativeApi;
  provider?: UpstreamProvider;
  base_url?: string;
  api_key?: string | null;
  model?: string | null;
  enabled?: boolean;
}

/** `POST /admin/upstreams/restore-mock` 返回;`created` 表本次是否真插入。 */
export interface RestoreMockResult {
  created: boolean;
  upstream: UpstreamOut;
}

/** `GET /admin/logs` 单条。对齐 `rosetta.server.controller.logs.LogOut`。 */
export interface LogOut {
  id: string;
  created_at: string;
  upstream: string | null;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  status: string;
  error: string | null;
  /** 客户端 "host:port"(本机回环也记;反代场景可能 null)。 */
  client_addr: string | null;
  /** 请求当时的 upstream.base_url 快照(mock 路径写 'mock://')。 */
  upstream_url: string | null;
  request_text: string | null;
  response_text: string | null;
}

export interface ListLogsParams {
  limit?: number;
  offset?: number;
  upstream?: string;
  /** polling 游标:只取 `created_at > since` 的记录(ISO 8601)。 */
  since?: string;
}

/** `GET /admin/logs` 返回结构。`total` 是同条件下的全表计数,用于分页器算 totalPages。 */
export interface LogListResponse {
  items: LogOut[];
  total: number;
}

export interface LogsConfigOut {
  log_content: "none" | "summary" | "full";
  page_size: 10 | 20 | 50 | 100;
}

export interface StatsOut {
  period: string;
  since: string;
  total_requests: number;
  success_rate: number;
  avg_latency_ms: number;
}

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    super(`HTTP ${status}: ${body.slice(0, 200)}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Tauri 壳内 true / vite dev 浏览器 false。 */
function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

let basePromise: Promise<string> | null = null;

/** 解析 server base URL。Tauri 内 invoke `get_server_url`;浏览器返 ""(走 vite proxy)。
 *  失败(endpoint.json 未写)会抛,调用方照常展示错误。 */
export async function apiBase(): Promise<string> {
  if (!inTauri()) return "";
  if (!basePromise) {
    basePromise = invoke<string>("get_server_url")
      .then((url) => url.replace(/\/$/, ""))
      .catch((e) => {
        basePromise = null; // 失败不缓存,允许重试
        throw e;
      });
  }
  return basePromise;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await apiBase();
  const resp = await fetch(base + path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ApiError(resp.status, text);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  ping(): Promise<{ ok: boolean }> {
    return request("/admin/ping");
  },
  status(): Promise<StatusResponse> {
    return request("/admin/status");
  },
  listUpstreams(): Promise<UpstreamOut[]> {
    return request("/admin/upstreams");
  },
  createUpstream(payload: UpstreamCreate): Promise<UpstreamOut> {
    return request("/admin/upstreams", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  deleteUpstream(id: string): Promise<void> {
    return request(`/admin/upstreams/${id}`, { method: "DELETE" });
  },
  listModelDefaults(): Promise<ModelDefaultsOut> {
    return request("/admin/upstreams/model-defaults");
  },
  testUpstream(id: string): Promise<UpstreamProbeOut> {
    return request(`/admin/upstreams/${id}/test`, {
      method: "POST",
    });
  },
  setModelDefaultUpstream(name: string, model: string): Promise<UpstreamOut> {
    const query = `?model=${encodeURIComponent(model)}`;
    return request(`/admin/upstreams/${encodeURIComponent(name)}/model-default${query}`, {
      method: "PUT",
    });
  },
  updateUpstream(id: string, payload: UpstreamUpdate): Promise<UpstreamOut> {
    return request(`/admin/upstreams/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },
  listLogs(params: ListLogsParams = {}): Promise<LogListResponse> {
    const q = new URLSearchParams();
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    if (params.offset !== undefined) q.set("offset", String(params.offset));
    if (params.upstream) q.set("upstream", params.upstream);
    if (params.since) q.set("since", params.since);
    const qs = q.toString();
    return request(`/admin/logs${qs ? "?" + qs : ""}`);
  },
  logsConfig(): Promise<LogsConfigOut> {
    return request("/admin/logs/config");
  },
  updateLogsConfig(payload: Partial<LogsConfigOut>): Promise<LogsConfigOut> {
    return request("/admin/logs/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  getProviderGuide(provider: string): Promise<{provider: string; content: string}> {
    return request(`/admin/upstreams/guide/${provider}`, { method: "GET" });
  },
  stats(period = "today"): Promise<StatsOut> {
    return request(`/admin/stats?period=${period}`);
  },
  restoreMockUpstream(force = false): Promise<RestoreMockResult> {
    return request(
      `/admin/upstreams/restore-mock?force=${force ? "true" : "false"}`,
      { method: "POST" },
    );
  },
};
