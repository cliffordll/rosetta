# rosetta 设计方案（TypeScript 版 · 已归档）

> ⚠️ **已归档 · 仅供对比参考**
> 项目确定走 Python 栈。本文档作为 TS 备选方案的快照保留,不再同步维护。
> 现行架构真源:[`../DESIGN.md`](../DESIGN.md)。

> 版本：v0.1-ts · 起草日期：2026-04-20
> 状态：已归档

---

## 0. 给 Python 背景读者的入门导览（先看这节）

你担心"TS 不熟，hold 不住"——这节就是让你判断实际成本。

### 0.1 心智映射

TS 是带类型注解的 JS，编译后就是 JS。它跟 Python 的大部分日常习惯可以直接对应：

| Python | TypeScript |
|---|---|
| `from foo import bar` | `import { bar } from "./foo"` |
| `class Foo(BaseModel):` (Pydantic) | `const Foo = z.object({...})` (Zod)，`type Foo = z.infer<typeof Foo>` |
| `async def f(): ...` | `async function f() { ... }` |
| `await x()` | `await x()` |
| `list[T]` | `T[]` 或 `Array<T>` |
| `dict[str, T]` | `Record<string, T>` 或 `Map<string, T>` |
| `Optional[T]` | `T \| undefined` 或 `T?` |
| `Union[A, B]` | `A \| B` |
| `Literal["a","b"]` + `match` | 字符串字面量 union + `switch`（更严：编译期穷举检查） |
| `asyncio.gather` | `Promise.all` |
| `httpx.AsyncClient` | 原生 `fetch` |
| `FastAPI` | `Hono`（接口风格很像） |
| `Pydantic` | `Zod` |
| `SQLAlchemy` | `Drizzle` |
| `typer` | `citty` |
| `uv` + `pyproject.toml` | `bun` + `package.json` |
| `pyinstaller --onefile` | `bun build --compile` |

### 0.2 核心差异点（容易踩）

1. **类型在编译期强制**：Pydantic 是运行时校验，TS 类型编译完就消失。**因此我们用 Zod 同时做运行时校验 + 类型推导**——schema 只写一次，两边都用。
2. **字符串 union 代替枚举**：`type Role = "user" | "assistant" | "tool"`，比 Python 的 `Literal` 更常用。`switch` / 三元上编译器会检查穷举。
3. **没有隐式 int/float 区分**：JS 只有 `number`。数据库里的 INTEGER 读出来就是 number，不用转。
4. **模块是文件级**：每个 `.ts` 文件就是一个模块，`export`/`import` 比 Python 的包/模块语义简单。
5. **null 与 undefined 两个空**：实践建议只用 `undefined`，Zod 的 `.optional()` 产出 `undefined`。
6. **并发模型**：单线程 event loop，和 Python `asyncio` 几乎一样。没有 GIL 问题是因为根本就一个线程。

### 0.3 为什么 TS 版在本项目反而更省心

- **一份 schema，五处使用**：`shared/` 包的 Zod schema 被 server（校验请求/解析响应）、sdk（类型化 HTTP 客户端）、cli（参数校验）、前端（表单 + API 调用）、tests（fixture 生成）**直接 import**。Python 版需要手维护 Pydantic 和前端 TS 两套，或引入 OpenAPI codegen。
- **翻译层类型强制**：三种 API 格式都有官方 TS SDK 提供类型定义，可直接 import。discriminated union + `switch` 让编译器强制你穷举所有 event / stop_reason / content block 分支，少写很多 bug。
- **工具链压到一条命令**：`bun` 替代 `node + npm + pnpm + tsc + tsx + jest + dotenv + esbuild`。比 Python 的 `uv + ruff + pytest + pyinstaller + uvicorn` 还少。

### 0.4 学习曲线估计（基于"Python 流畅"基准）

| 内容 | 时间 |
|---|---|
| 读懂并能改本项目的 TS 语法 | 1–2 天（AI 辅助） |
| 写 Hono 路由 / Zod schema / Drizzle 查询 | 2–3 天 |
| 翻译层的 discriminated union 玩熟 | 3–5 天（最难的部分） |
| 整体流畅 | 2 周 |

结论：**hold 得住**。关键是本项目的复杂度集中在"业务逻辑"（翻译矩阵），而业务逻辑在任何语言里都一样难。TS 语法只是壳。

---

## 1. 项目定位

**一个本地跑的 LLM API 格式转换中枢，外加桌面管理端（GUI）和命令行工具（CLI）。**

核心能力是 **三种主流 LLM API 格式的任意互译**：

- **Claude Messages API**（`POST /v1/messages`）
- **OpenAI Chat Completions API**（`POST /v1/chat/completions`）
- **OpenAI Responses API**（`POST /v1/responses`）

客户端用哪种格式调用都行；上游是哪种格式也都行。代理负责 **3×3 翻译矩阵**——同格式直通，异格式经内部 IR 双向翻译，流式/非流式都支持。

派生价值同 Python 版：跨生态调用、切换上游、集中管理、零侵入。

---

## 2. 核心决策汇总

| # | 决策项 | 选择 | 备注 |
|---|---|---|---|
| 1 | 代理类型 | 应用层 API 中转 | 同 Python 版 |
| 2 | 上游支持 | Anthropic + OpenAI + OpenRouter + 自定义 | |
| 3 | 对外 API 格式 | Claude + Chat Completions + Responses 全支持 | 三格式任意互译 |
| 4 | 翻译引擎 | 自研核心（3×3 IR 翻译矩阵） | 官方 TS SDK 提供字段类型，减少手写 |
| 5 | 运行时 | **Bun** 1.x | 内置 TS / SQLite / 测试 / bundler / 单文件编译 |
| 6 | Web 框架 | **Hono** | FastAPI 风格，SSE 原生支持 |
| 7 | Schema 校验 | **Zod** | 运行时 + 类型推导一体 |
| 8 | 数据库 | SQLite via `bun:sqlite` | 内置驱动，无需外部依赖 |
| 9 | ORM | **Drizzle** | 轻量、类型安全、SQL 贴合度高 |
| 10 | CLI 框架 | **citty** | 简洁声明式，类似 typer |
| 11 | 打包 | `bun build --compile` | 直出单文件 exe，跨平台 |
| 12 | Monorepo | Bun workspaces | package.json 的 `workspaces` 字段 |
| 13 | Server 生命周期 | Sidecar + 引用计数（模型 ②） | 同 Python 版 |
| 14 | 管理面实时性 | 普通 HTTP | v0 不做 WebSocket |
| 15 | 数据面实时性 | SSE 透传 | |
| 16 | 桌面外壳 | Tauri 2.x（Rust） | **不变**，sidecar 换成 Bun 二进制 |
| 17 | 前端框架 | React + TS + Vite + Tailwind + shadcn/ui | |
| 18 | 平台 | Windows 优先 | |

---

## 3. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                              用户侧                               │
│                                                                  │
│  ┌────────────┐      ┌──────────┐      ┌────────────────────┐  │
│  │ 客户端应用  │      │ 桌面 GUI  │      │    终端 CLI          │  │
│  │ (VS Code / │      │(Tauri +   │      │  (citty)            │  │
│  │ Cursor /   │      │ React)    │      │                      │  │
│  │ 任何 SDK)  │      │          │      │                      │  │
│  └──────┬─────┘      └─────┬────┘      └─────────┬───────────┘  │
│         │                  │                      │              │
│ Claude / OpenAI          管理面调用             管理面调用         │
│  Chat / Responses        (HTTP /admin/*)        (HTTP /admin/*)   │
│  (HTTP + SSE)                                                    │
│         │                  │                      │              │
└─────────┼──────────────────┼──────────────────────┼──────────────┘
          │                  │                      │
          ▼                  ▼                      ▼
┌──────────────────────────────────────────────────────────────────┐
│            rosetta-server （TypeScript + Bun + Hono）           │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ 数据面路由        │  │ 管理面路由    │  │ 运行时            │   │
│  │ /v1/messages      │  │ /admin/*     │  │ endpoint.json     │   │
│  │ /v1/chat/compl..  │  │              │  │ pid lockfile      │   │
│  │ /v1/responses     │  │              │  │ parent-watcher    │   │
│  └──────┬───────────┘  └──────┬───────┘  └──────────────────┘   │
│         │                     │                                   │
│  ┌──────▼─────────────────────▼──────┐                           │
│  │       Services                    │                           │
│  │  forwarder  provider  router      │                           │
│  │  logger     stats                 │                           │
│  └──────┬────────────────────────────┘                           │
│         │                                                         │
│  ┌──────▼──────────────┐   ┌─────────────────────────────┐      │
│  │  Translation 3×3    │   │  SQLite (bun:sqlite + Drizzle)│    │
│  │  IR + 3 adapter     │   │  providers/keys/routes/logs │      │
│  └──────┬──────────────┘   └─────────────────────────────┘      │
│         │                                                         │
└─────────┼─────────────────────────────────────────────────────────┘
          │ HTTPS (fetch)
          ▼
┌──────────────────────────────────────────────────────────────────┐
│                          上游 LLM 服务                            │
│  Anthropic   OpenAI (Chat/Responses)   OpenRouter   中转站        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 两条独立通道：数据面 vs 管理面

|  | **数据面（Data Plane）** | **管理面（Control Plane）** |
|---|---|---|
| 谁在用 | 客户端应用 | 你自己（GUI / CLI） |
| 端点 | `/v1/*`（Claude + OpenAI 兼容） | `/admin/*` |
| 典型调用 | `POST /v1/messages` / `/v1/chat/completions` / `/v1/responses` | `GET /admin/providers` 等 |
| 流量特征 | 高频、长连接、**必须 SSE** | 低频、短请求 |
| 认证 | 本地 key，`x-api-key` 或 `Authorization: Bearer` 都接受 | token（从 `endpoint.json` 读） |

---

## 5. 进程模型与 sidecar 架构

```
┌──────────────────────────────────┐
│  Rosetta.exe (Tauri 外壳)       │
│     │                            │
│     ├── msedgewebview2.exe       │  ← 渲染 React
│     │                            │
│     └── rosetta-server.exe     │  ← sidecar：Bun 编译
│         (bun build --compile)    │     绑 127.0.0.1:随机端口
└──────────────────────────────────┘
```

### 打包产物

| 二进制 | 怎么来 | 内容 | 大小估 |
|---|---|---|---|
| `rosetta-server.exe` | `bun build --compile packages/server/src/main.ts` | Bun runtime + Hono + SQLite + 翻译层 | ~90 MB |
| `rosetta.exe` (CLI) | `bun build --compile packages/cli/src/main.ts` | Bun runtime + citty + SDK | ~85 MB |
| `Rosetta.exe` (GUI) | `tauri build` + 前端 + sidecar | Rust 外壳 + WebView2 + 前端 + server exe | ~130-160 MB |

> 注：Bun 编译产物都带完整 runtime，单个体积大。可选优化：**CLI 和 server 合并为同一个二进制**，通过 `argv[1]` 分派子命令（`rosetta serve` vs `rosetta status`），可节省一个 ~85MB。v0 不做，简单优先。

---

## 6. Server 生命周期（模型 ②：引用计数）

与 Python 版完全一致。核心原则：

> whoever needs server, checks if running, spawns it if not; last one out turns off the lights.

### endpoint.json

Server 启动时写 `~/.rosetta/endpoint.json`：

```json
{ "url": "http://127.0.0.1:62538", "token": "...", "pid": 12345 }
```

### 引用计数实现

```typescript
// runtime/watcher.ts
export async function watchParent(pid: number): Promise<never> {
  while (true) {
    await Bun.sleep(3000);
    if (!isProcessAlive(pid)) {
      process.exit(0);
    }
  }
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);  // 信号 0 只探测，不真发
    return true;
  } catch {
    return false;
  }
}
```

v0 只跟踪**单个** parent pid（先启动的那个）。v1 可以做多 pid 集合。

---

## 7. 项目布局（monorepo）

```
rosetta/
├── README.md
├── DESIGN.md                     # Python 版设计
├── DESIGN_TS.md                  # 本文档
├── .gitignore
├── package.json                  # bun workspaces 根
├── bun.lockb
├── tsconfig.base.json            # 共享 TS 配置
│
└── packages/
    ├── shared/                   # 跨包共享的 Zod schema —— TS 版的核心红利
    │   └── src/
    │       ├── claude.ts         # Claude Messages request/response schema
    │       ├── openai-chat.ts    # OpenAI Chat Completions
    │       ├── openai-resp.ts    # OpenAI Responses
    │       ├── admin.ts          # 管理面：Provider / Key / Route / Log
    │       └── index.ts
    │
    ├── server/                   # Bun + Hono —— v0 先做这个
    │   ├── package.json
    │   └── src/
    │       ├── main.ts           # 入口：parseArgs + 启动 Hono + 生命周期
    │       ├── app.ts            # Hono app factory
    │       ├── db/
    │       │   ├── schema.ts     # Drizzle 表定义
    │       │   ├── client.ts     # sqlite 连接 + migrations
    │       │   └── migrations/
    │       ├── api/
    │       │   ├── admin.ts      # /admin/*
    │       │   ├── proxy.ts      # /v1/messages, /chat/completions, /responses
    │       │   └── auth.ts       # middleware：本地 key 验证（两种头）
    │       ├── services/
    │       │   ├── forwarder.ts  # 调度：直通 or 翻译
    │       │   ├── provider.ts   # CRUD
    │       │   ├── router.ts     # 模型→provider
    │       │   ├── logger.ts     # 请求日志（内存 queue + 批量 flush）
    │       │   └── stats.ts
    │       ├── translation/      # 核心翻译层
    │       │   ├── ir.ts         # RequestIR / ResponseIR / StreamEventIR
    │       │   ├── claude.ts     # Claude adapter（inbound/outbound/stream）
    │       │   ├── openai-chat.ts
    │       │   └── openai-resp.ts
    │       ├── runtime/
    │       │   ├── endpoint.ts   # 读/写 endpoint.json
    │       │   ├── lockfile.ts   # pid-file
    │       │   └── watcher.ts    # parent-pid 监控
    │       └── config.ts         # 环境变量 / CLI flag
    │
    ├── sdk/                      # HTTP 客户端（CLI + GUI 前端共用）
    │   └── src/
    │       ├── client.ts         # ProxyClient 类，包装 /admin/* 调用
    │       ├── discover.ts       # 读 endpoint.json；不存在就 spawn server
    │       └── index.ts
    │
    ├── cli/                      # citty 终端命令行
    │   └── src/
    │       ├── main.ts           # defineCommand + runMain
    │       └── commands/
    │           ├── status.ts
    │           ├── start.ts
    │           ├── stop.ts
    │           ├── provider.ts
    │           ├── key.ts
    │           └── logs.ts
    │
    ├── app/                      # 前端（Vite + React）
    │   ├── package.json
    │   ├── vite.config.ts
    │   ├── tailwind.config.ts
    │   └── src/
    │       ├── main.tsx
    │       ├── App.tsx
    │       ├── api/              # 直接 import @rosetta/sdk，不用 codegen
    │       ├── pages/
    │       │   ├── Dashboard.tsx
    │       │   ├── Providers.tsx
    │       │   ├── Routes.tsx
    │       │   ├── Keys.tsx
    │       │   └── Logs.tsx
    │       └── components/       # shadcn/ui
    │
    └── desktop/                  # Tauri 外壳（Rust，保持不变）
        ├── package.json
        └── src-tauri/
            ├── Cargo.toml
            ├── tauri.conf.json   # externalBin = rosetta-server
            └── src/
                ├── main.rs
                └── sidecar.rs
```

> **`shared/` 是 TS 版的关键**：Zod schema 在这里定义一次，五个包（server 校验、sdk 解析、cli 参数、app 表单、测试 fixture）全部 `import { CreateProviderInput } from "@rosetta/shared"` 直接用。改一处，编译器强制全链路同步。

---

## 8. Server 详细设计

### 8.1 API 接口清单

**管理面**（同 Python 版，端点列表不变）：

```
GET    /admin/ping
GET    /admin/status
GET    /admin/providers
POST   /admin/providers
GET    /admin/providers/:id
PUT    /admin/providers/:id
DELETE /admin/providers/:id
POST   /admin/providers/:id/test
GET    /admin/routes
PUT    /admin/routes
GET    /admin/keys
POST   /admin/keys
DELETE /admin/keys/:id
GET    /admin/logs?limit=50&offset=0
GET    /admin/stats?period=today
POST   /admin/shutdown
```

**数据面**：

```
POST /v1/messages                    Claude Messages 格式
POST /v1/chat/completions            OpenAI Chat Completions 格式
POST /v1/responses                   OpenAI Responses 格式
                                      非流 → JSON，流式 → SSE
GET  /v1/models?format=claude|openai 合并模型列表，格式随 ?format=
```

鉴权：`x-api-key` 或 `Authorization: Bearer` 都接受。

**Hono 路由示例**：

```typescript
// api/proxy.ts
import { Hono } from "hono";
import { streamSSE } from "hono/streaming";
import { ClaudeMessagesRequest } from "@rosetta/shared";

export const proxy = new Hono<{ Variables: { keyId: number } }>()
  .use("*", authMiddleware)
  .post("/v1/messages", async (c) => {
    const body = ClaudeMessagesRequest.parse(await c.req.json());
    const provider = await router.select(body.model);

    if (body.stream) {
      return streamSSE(c, async (stream) => {
        for await (const evt of forwarder.forwardStream(body, provider, "claude")) {
          await stream.writeSSE({ event: evt.type, data: JSON.stringify(evt.data) });
        }
      });
    }
    return c.json(await forwarder.forward(body, provider, "claude"));
  })
  .post("/v1/chat/completions", /* ... */)
  .post("/v1/responses", /* ... */);
```

### 8.2 数据模型（Drizzle）

```typescript
// db/schema.ts
import { sqliteTable, integer, text } from "drizzle-orm/sqlite-core";
import { sql } from "drizzle-orm";

export const providers = sqliteTable("providers", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").unique().notNull(),
  type: text("type", { enum: ["anthropic", "openai", "openrouter", "custom"] }).notNull(),
  format: text("format", { enum: ["claude", "openai-chat", "openai-resp"] }).notNull(),
  baseUrl: text("base_url"),
  apiKey: text("api_key").notNull(),
  enabled: integer("enabled", { mode: "boolean" }).default(true),
  createdAt: text("created_at").default(sql`CURRENT_TIMESTAMP`),
});

export const keys = sqliteTable("keys", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").unique().notNull(),
  key: text("key").unique().notNull(),
  expiresAt: text("expires_at"),
  createdAt: text("created_at").default(sql`CURRENT_TIMESTAMP`),
  revokedAt: text("revoked_at"),
});

export const routes = sqliteTable("routes", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  modelGlob: text("model_glob").notNull(),
  providerId: integer("provider_id").references(() => providers.id).notNull(),
  priority: integer("priority").default(0),
});

export const logs = sqliteTable("logs", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  createdAt: text("created_at").default(sql`CURRENT_TIMESTAMP`),
  keyId: integer("key_id").references(() => keys.id),
  providerId: integer("provider_id").references(() => providers.id),
  model: text("model"),
  inputTokens: integer("input_tokens"),
  outputTokens: integer("output_tokens"),
  latencyMs: integer("latency_ms"),
  status: text("status"),       // ok / error / timeout
  error: text("error"),
});
```

注：`providers.format` 是 **TS 版新增字段**——Python 版省略了，靠 `type` 隐含。TS 版因为有 3 种格式 × 4 种 type（anthropic/openai/openrouter/custom），用独立字段标明该 provider 说哪种 API 更清晰。例如 `type=custom, format=claude` 表示"中转站说 Claude 格式"。

### 8.3 翻译层（IR + 3×3 矩阵）

**核心不变**：一个 IR + 三个 adapter，对角线直通，其余 6 格走 `inAdapter.toIR → outAdapter.fromIR` 串联。概念见 [`DESIGN.md §8.3`](./DESIGN.md#83-翻译层策略3x3-矩阵--ir) 的矩阵表和字段对照表。

#### IR 定义（Zod）

```typescript
// translation/ir.ts
import { z } from "zod";

export const TextBlock = z.object({ type: z.literal("text"), text: z.string() });
export const ImageBlock = z.object({ type: z.literal("image"), source: z.unknown() });
export const ToolUseBlock = z.object({
  type: z.literal("tool_use"),
  id: z.string(),
  name: z.string(),
  input: z.unknown(),
});
export const ToolResultBlock = z.object({
  type: z.literal("tool_result"),
  toolUseId: z.string(),
  content: z.unknown(),
  isError: z.boolean().optional(),
});

export const ContentBlock = z.discriminatedUnion("type", [
  TextBlock, ImageBlock, ToolUseBlock, ToolResultBlock,
]);

export const Message = z.object({
  role: z.enum(["user", "assistant", "tool"]),
  content: z.array(ContentBlock),
});

export const RequestIR = z.object({
  model: z.string(),
  system: z.string().optional(),
  messages: z.array(Message),
  tools: z.array(z.object({
    name: z.string(),
    description: z.string().optional(),
    inputSchema: z.unknown(),
  })).optional(),
  toolChoice: z.union([z.literal("auto"), z.literal("any"), z.literal("none"),
                       z.object({ name: z.string() })]).optional(),
  sampling: z.object({
    temperature: z.number().optional(),
    topP: z.number().optional(),
    maxTokens: z.number().optional(),
    stop: z.array(z.string()).optional(),
  }).default({}),
  stream: z.boolean().default(false),
  _extras: z.record(z.unknown()).optional(),
});

export type RequestIR = z.infer<typeof RequestIR>;

// Stream Event IR（以 Claude 的事件粒度为基准，最细）
export const StreamEventIR = z.discriminatedUnion("type", [
  z.object({ type: z.literal("message_start"), id: z.string(), model: z.string() }),
  z.object({ type: z.literal("content_block_start"), index: z.number(), block: ContentBlock }),
  z.object({ type: z.literal("content_block_delta"), index: z.number(),
             delta: z.union([
               z.object({ type: z.literal("text_delta"), text: z.string() }),
               z.object({ type: z.literal("input_json_delta"), partialJson: z.string() }),
             ]) }),
  z.object({ type: z.literal("content_block_stop"), index: z.number() }),
  z.object({ type: z.literal("message_delta"), stopReason: z.string().optional(),
             usage: z.object({ inputTokens: z.number(), outputTokens: z.number() }).optional() }),
  z.object({ type: z.literal("message_stop") }),
]);
```

#### Adapter 接口

```typescript
// translation/adapter.ts
export interface FormatAdapter<Req, Res> {
  // 客户端方向：解析请求到 IR
  parseRequest(raw: unknown): RequestIR;
  // 上游方向：从 IR 序列化成该格式
  serializeRequest(ir: RequestIR): Req;
  // 非流式响应
  parseResponse(raw: unknown): ResponseIR;
  serializeResponse(ir: ResponseIR): Res;
  // 流式：上游 SSE → IR 事件流
  parseStream(sse: AsyncIterable<RawSSE>): AsyncIterable<StreamEventIR>;
  // 流式：IR 事件流 → 客户端 SSE
  serializeStream(events: AsyncIterable<StreamEventIR>): AsyncIterable<RawSSE>;
}
```

三个实现：`translation/claude.ts` / `openai-chat.ts` / `openai-resp.ts`。每个实现内部可以**复用官方 TS SDK 的类型**（`@anthropic-ai/sdk` / `openai`）减少 schema 手写量。

#### Forwarder 主流程

```typescript
// services/forwarder.ts
export async function* forwardStream(
  raw: unknown,
  provider: Provider,
  clientFormat: Format,
): AsyncIterable<RawSSE> {
  const inAdapter = adapters[clientFormat];
  const outAdapter = adapters[provider.format];

  if (clientFormat === provider.format) {
    yield* passthroughStream(raw, provider);  // httpx 原样转发
    return;
  }

  const ir = inAdapter.parseRequest(raw);
  applyRouting(ir);  // e.g. 模型映射
  const upstreamReq = outAdapter.serializeRequest(ir);

  const upstreamSSE = fetchStream(provider.baseUrl, upstreamReq, provider.apiKey);
  const irEvents = outAdapter.parseStream(upstreamSSE);
  yield* inAdapter.serializeStream(irEvents);
}
```

#### Responses API 有状态特性降级

同 Python 版（§8.3 表格）：`store=true` / `previous_response_id` / `background` / 内置 tools 在直通时保留，在异格式翻译时降级或报 400。

#### 实施优先级

- v0.1：Claude ↔ Chat Completions 双向
- v0.2：加入 Responses API
- 直通三格对角线：day-0 可用

### 8.4 路由规则 / 8.5 本地 key

逻辑与 Python 版完全一致。本地 key 格式 `rs_xxxxxxxx...`。

---

## 9. SDK 设计

```typescript
// sdk/src/client.ts
import type { Provider, CreateProviderInput } from "@rosetta/shared";
import { Provider as ProviderSchema } from "@rosetta/shared";
import { z } from "zod";

export class ProxyClient {
  constructor(private url: string, private token: string) {}

  static async discover(): Promise<ProxyClient> {
    const endpoint = await discoverOrSpawn();  // discover.ts
    return new ProxyClient(endpoint.url, endpoint.token);
  }

  async listProviders(): Promise<Provider[]> {
    const res = await this.get("/admin/providers");
    return z.array(ProviderSchema).parse(res);
  }

  async createProvider(input: CreateProviderInput): Promise<Provider> {
    const res = await this.post("/admin/providers", input);
    return ProviderSchema.parse(res);
  }

  private async get(path: string) { /* fetch + auth header */ }
  private async post(path: string, body: unknown) { /* ... */ }
}
```

**关键红利**：`Provider` 类型从 `@rosetta/shared` 直接来。server、sdk、cli、app 用的是同一份 Zod schema，改 schema 所有地方编译器强制跟随。

---

## 10. CLI 设计

```typescript
// cli/src/main.ts
import { defineCommand, runMain } from "citty";

const main = defineCommand({
  meta: { name: "rosetta", version: "0.1.0", description: "LLM API format converter" },
  subCommands: {
    status:   () => import("./commands/status").then(m => m.default),
    start:    () => import("./commands/start").then(m => m.default),
    stop:     () => import("./commands/stop").then(m => m.default),
    serve:    () => import("./commands/serve").then(m => m.default),
    provider: () => import("./commands/provider").then(m => m.default),
    key:      () => import("./commands/key").then(m => m.default),
    logs:     () => import("./commands/logs").then(m => m.default),
  },
});

runMain(main);
```

子命令示例：

```typescript
// cli/src/commands/provider.ts
import { defineCommand } from "citty";
import { ProxyClient } from "@rosetta/sdk";

export default defineCommand({
  meta: { name: "provider", description: "manage upstream providers" },
  subCommands: {
    list: defineCommand({
      async run() {
        const client = await ProxyClient.discover();
        const providers = await client.listProviders();
        console.table(providers);
      },
    }),
    add: defineCommand({
      args: {
        name:   { type: "string", required: true },
        type:   { type: "string", required: true },
        format: { type: "string", required: true },
        apiKey: { type: "string", required: true },
      },
      async run({ args }) {
        const client = await ProxyClient.discover();
        await client.createProvider(args);
        console.log("added");
      },
    }),
  },
});
```

可用命令与 Python 版一致（status / start / stop / serve / provider / key / logs / stats）。

---

## 11. GUI 设计

### 页面清单（v0）

1. Dashboard — 状态 / 今日请求 / 错误率
2. Providers — 表格 + Modal（shadcn/ui）
3. Routes — 路由规则（拖拽 v1）
4. Keys — 本地 key
5. Logs — 日志列表 + 筛选

### Tauri 侧（Rust，不变）

- spawn `rosetta-server.exe` 并传 `--parent-pid`
- emit URL + token 到前端
- 窗口状态记忆 + 托盘 + 自动更新

Tauri 配置：

```json
// packages/desktop/src-tauri/tauri.conf.json
{
  "bundle": {
    "externalBin": ["binaries/rosetta-server"]
  }
}
```

把 `bun build --compile` 出来的 exe 放到 `binaries/` 即可。

### 前端 Platform 抽象

```typescript
interface Platform {
  getBackendUrl(): string;
  getBackendToken(): string;
  openExternalLink(url: string): void;
  quit(): void;
}
```

Tauri 实现：走 `@tauri-apps/api`。Web 版实现：原生 fetch + window.open。

---

## 12. 部署与打包

### 开发

```bash
# 装依赖（一次性搞定所有 workspace）
bun install

# 启 server（watch 模式）
cd packages/server
bun run --watch src/main.ts

# 启前端 dev server
cd packages/app
bun run dev

# 启 Tauri dev（自动拉起前端 + sidecar）
cd packages/desktop
bun run tauri dev
```

### 打包

```bash
# 1. server 单文件 exe
bun build --compile --minify --sourcemap \
  --outfile=dist/rosetta-server.exe \
  packages/server/src/main.ts

# 2. CLI 单文件 exe
bun build --compile --minify \
  --outfile=dist/rosetta.exe \
  packages/cli/src/main.ts

# 3. 前端
cd packages/app && bun run build

# 4. Tauri 桌面包
cp dist/rosetta-server.exe packages/desktop/src-tauri/binaries/
cd packages/desktop && bun run tauri build
# → Rosetta-setup.exe
```

Bun 支持 cross-compile：在任何系统上可 `--target=bun-windows-x64` 出 Windows exe。

---

## 13. 风险与待决议项

### TS 特有风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **Bun Windows 稳定性** | 罕见 IO bug | Hono / Drizzle / Zod 都跑 Node，真碰到切 runtime 不改业务代码。2026 年 Bun 已 GA 较成熟 |
| **`bun:sqlite` 同步 API** | 重写入阻塞 event loop | 日志批量写 + 小事务；实在不行换 `@libsql/client`（原生异步） |
| **Discriminated union 学习曲线** | 翻译层事件类型复杂 | AI 辅助；Anthropic/OpenAI 官方 TS SDK 提供大量现成类型 |
| **单文件体积偏大** | Bun exe ~90MB vs PyInstaller 40-80MB | 可接受；考虑合并 CLI 和 server |
| **Bun watch 偶发不重启** | dev 体验 | 用 Node + tsx 替代 dev 时的 watch |

### 通用风险（与 Python 版相同）

| 风险 | 缓解 |
|---|---|
| 自研翻译层边缘 case | 金标样本 + E2E 测试；无法映射字段落 `_extras` |
| 流式状态机 bug | 每个 adapter fixture-based 回归测试 |
| Responses 有状态特性 | 明确降级策略（§8.3） |
| 上游 API 版本漂移 | 直通只检必要字段；翻译路径未知字段进 `_extras` |
| SQLite 并发写 | 内存 queue + 批量 flush |
| Windows 子进程 kill | Tauri 用 JobObject；watcher.ts 做保底 |

### 待决议

- [ ] **Bun vs Node**：Bun 简洁新；Node 老练但工具链多装几个。v0 先 Bun，真出问题再切。
- [ ] **Drizzle vs 原生 SQL**：Drizzle 类型安全；原生 SQL 透明。倾向 Drizzle。
- [ ] **CLI 和 server 合并单 exe**：省一个 85MB，但 argv 分派稍复杂。v0 不合，v1 考虑。
- [ ] **GUI 主题色 / 多用户 / 配置导入导出 / stats 粒度 / 日志 TTL**：同 Python 版。

---

## 14. 参考资料

- [Bun 文档](https://bun.sh/docs) — runtime / compile / sqlite / test
- [Hono 文档](https://hono.dev/) — 特别看 Streaming 一章
- [Drizzle ORM](https://orm.drizzle.team/) — SQLite 驱动
- [Zod](https://zod.dev/)
- [citty](https://github.com/unjs/citty)
- [`@anthropic-ai/sdk`](https://github.com/anthropics/anthropic-sdk-typescript) — 可直接 import 其 types
- [`openai` Node SDK](https://github.com/openai/openai-node)
- [Tauri 2.x sidecar](https://v2.tauri.app/develop/sidecar/)
- [`DESIGN.md`](./DESIGN.md) — Python 版（同结构对照阅读）

---

_本文档和 DESIGN.md 是二选一的实施方案。选定其一后，另一份作为参考保留，不再同步更新。_
