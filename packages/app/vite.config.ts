import { existsSync, readFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

function resolveServerUrl(): string | null {
  const fromEnv = process.env.VITE_API_URL;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();

  const endpointPath = path.join(os.homedir(), ".rosetta", "endpoint.json");
  if (!existsSync(endpointPath)) return null;
  try {
    const raw = readFileSync(endpointPath, "utf-8");
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      "url" in parsed &&
      typeof (parsed as { url: unknown }).url === "string"
    ) {
      return (parsed as { url: string }).url;
    }
  } catch {
    // fallthrough
  }
  return null;
}

export default defineConfig(({ command }) => {
  // 只在 dev server 模式下算代理目标;build 不需要,避免噪声日志
  const target = command === "serve" ? resolveServerUrl() : null;
  if (command === "serve") {
    if (!target) {
      console.warn(
        "[rosetta] 未发现 server URL;先跑 `rosetta start`,或设 VITE_API_URL 环境变量。" +
          " /admin 与 /v1 代理将不可用。",
      );
    } else {
      console.log(`[rosetta] dev proxy /admin + /v1 → ${target}`);
    }
  }

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      strictPort: false,
      proxy: target
        ? {
            "/admin": { target, changeOrigin: true },
            "/v1": { target, changeOrigin: true, ws: true },
          }
        : undefined,
    },
  };
});
