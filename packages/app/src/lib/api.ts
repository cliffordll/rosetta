/**
 * rosetta server admin API 薄封装。
 *
 * - 路径用相对(`/admin/*`),dev 靠 vite.config proxy 转到 server,prod(Tauri 内)
 *   同 origin 直通
 * - 类型手写,对齐 `rosetta/server/admin/*.py` 的 Pydantic schema;endpoints 少
 *   (status + 4 provider 操作),5.2 不引 OpenAPI codegen
 */

export type ProviderType = "anthropic" | "openai" | "openrouter" | "custom";

/** 客户端侧 API 形态;与 `rosetta.shared.formats.Format` 的 str 值严格一致。 */
export const Format = {
  MESSAGES: "messages",
  CHAT_COMPLETIONS: "completions",
  RESPONSES: "responses",
} as const;
export type Format = (typeof Format)[keyof typeof Format];

/** 三格式各自的默认模型 + 下拉候选(5.3 硬编码;v1+ 再引入动态发现)。 */
export const DEFAULT_MODELS: Record<Format, string> = {
  [Format.MESSAGES]: "claude-haiku-4-5",
  [Format.CHAT_COMPLETIONS]: "gpt-4o-mini",
  [Format.RESPONSES]: "gpt-4o-mini",
};

export const MODEL_CHOICES: Record<Format, string[]> = {
  [Format.MESSAGES]: ["claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5"],
  [Format.CHAT_COMPLETIONS]: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
  [Format.RESPONSES]: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
};

/** provider.type → 上游原生 format(对齐后端 `PROVIDER_NATIVE_FORMAT`)。 */
export const PROVIDER_NATIVE_FORMAT: Record<string, Format> = {
  anthropic: Format.MESSAGES,
  openai: Format.CHAT_COMPLETIONS,
  openrouter: Format.CHAT_COMPLETIONS,
};

export interface StatusResponse {
  version: string;
  uptime_ms: number;
  providers_count: number;
}

export interface ProviderOut {
  id: number;
  name: string;
  type: string;
  base_url: string | null;
  enabled: boolean;
  created_at: string;
}

export interface ProviderCreate {
  name: string;
  type: ProviderType;
  api_key: string;
  base_url?: string | null;
  enabled?: boolean;
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
  listProviders(): Promise<ProviderOut[]> {
    return request("/admin/providers");
  },
  createProvider(payload: ProviderCreate): Promise<ProviderOut> {
    return request("/admin/providers", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  deleteProvider(id: number): Promise<void> {
    return request(`/admin/providers/${id}`, { method: "DELETE" });
  },
};
