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

/** 客户端侧 API 协议;与 `rosetta.shared.protocols.Protocol` 的 str 值严格一致。 */
export const Protocol = {
  MESSAGES: "messages",
  CHAT_COMPLETIONS: "completions",
  RESPONSES: "responses",
} as const;
export type Protocol = (typeof Protocol)[keyof typeof Protocol];

export type UpstreamProtocol = Protocol;

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

/** 三协议各自的默认模型 + 下拉候选(5.3 硬编码;v1+ 再引入动态发现)。 */
export const DEFAULT_MODELS: Record<Protocol, string> = {
  [Protocol.MESSAGES]: "claude-haiku-4-5",
  [Protocol.CHAT_COMPLETIONS]: "gpt-4o-mini",
  [Protocol.RESPONSES]: "gpt-4o-mini",
};

export const MODEL_CHOICES: Record<Protocol, string[]> = {
  [Protocol.MESSAGES]: ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5"],
  [Protocol.CHAT_COMPLETIONS]: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
  [Protocol.RESPONSES]: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
};

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
  protocol: string;
  provider: string;
  base_url: string;
  enabled: boolean;
  created_at: string;
}

export interface UpstreamCreate {
  name: string;
  protocol: UpstreamProtocol;
  provider: UpstreamProvider;
  api_key?: string;
  base_url: string;
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
}

export interface ListLogsParams {
  limit?: number;
  offset?: number;
  upstream?: string;
  /** polling 游标:只取 `created_at > since` 的记录(ISO 8601)。 */
  since?: string;
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
  listLogs(params: ListLogsParams = {}): Promise<LogOut[]> {
    const q = new URLSearchParams();
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    if (params.offset !== undefined) q.set("offset", String(params.offset));
    if (params.upstream) q.set("upstream", params.upstream);
    if (params.since) q.set("since", params.since);
    const qs = q.toString();
    return request(`/admin/logs${qs ? "?" + qs : ""}`);
  },
  restoreMockUpstream(force = false): Promise<RestoreMockResult> {
    return request(
      `/admin/upstreams/restore-mock?force=${force ? "true" : "false"}`,
      { method: "POST" },
    );
  },
};
