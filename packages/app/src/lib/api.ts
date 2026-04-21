/**
 * rosetta server admin API 薄封装。
 *
 * - 路径用相对(`/admin/*`),dev 靠 vite.config proxy 转到 server,prod(Tauri 内)
 *   同 origin 直通
 * - 类型手写,对齐 `rosetta/server/admin/*.py` 的 Pydantic schema;endpoints 少
 *   (status + 4 provider 操作),5.2 不引 OpenAPI codegen
 */

export type ProviderType = "anthropic" | "openai" | "openrouter" | "custom";

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
