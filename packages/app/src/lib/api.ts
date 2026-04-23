/**
 * rosetta server admin API 薄封装。
 *
 * - 路径用相对(`/admin/*`),dev 靠 vite.config proxy 转到 server,prod(Tauri 内)
 *   同 origin 直通
 * - 类型手写,对齐 `rosetta/server/controller/*.py` 的 Pydantic schema;endpoints 少
 *   (status + 3 upstream 操作),5.2 不引 OpenAPI codegen
 */

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
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
  restoreMockUpstream(force = false): Promise<RestoreMockResult> {
    return request(
      `/admin/upstreams/restore-mock?force=${force ? "true" : "false"}`,
      { method: "POST" },
    );
  },
};
