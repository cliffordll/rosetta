import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

import { rosettaProxy } from "./vite-plugin-rosetta-proxy";

// /admin + /v1 的转发交给 `rosettaProxy` 插件(per-request 动态读 endpoint.json);
// 不用 server.proxy,避免 vite 启动时固化 target 后 server 换端口就 502。
export default defineConfig(() => ({
  plugins: [react(), tailwindcss(), rosettaProxy()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
  },
}));
