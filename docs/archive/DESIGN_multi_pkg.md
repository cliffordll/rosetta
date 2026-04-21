# rosetta 设计方案（多包布局 · 已归档）

> ⚠️ **已归档 · 仅供对比参考**
> 本文档是"三包拆分"布局的早期草稿，已被单包布局的 [`DESIGN.md`](../DESIGN.md) 取代。
> 已知与 `DESIGN.md` 的关键分歧：
> - 认证模型：本文档保留 `keys` 表 / 本地 key；`DESIGN.md` 已删除（loopback-only + 上游 key 透传）
> - `/v1/models?format=` 参数值：本文档 `claude|openai`；`DESIGN.md` `messages|completions|responses`
> - direct 模式（`--base-url` 旁路）：本文档未覆盖；`DESIGN.md` §8.6 已定义
> - Python 包名风格：本文档 `rosetta_server`；`DESIGN.md` `rosetta.server`
> - `logs` 表旧名 `request_logs`（本文档 §8.2 Schema 已同步新名）
>
> 实现请以 `DESIGN.md` 为唯一真源。本文内容不再维护。

> 版本：v0.1 · 起草日期：2026-04-20
> 状态：已归档

---

## 1. 项目定位

**一个本地跑的 LLM API 格式转换中枢，外加桌面管理端（GUI）和命令行工具（CLI）。**

核心能力是 **三种主流 LLM API 格式的任意互译**：

- **Claude Messages API**（`POST /v1/messages`）
- **OpenAI Chat Completions API**（`POST /v1/chat/completions`）
- **OpenAI Responses API**（`POST /v1/responses`）

客户端用哪种格式调用都行；上游是哪种格式也都行。代理负责做 **3×3 翻译矩阵**——同格式直通（httpx 透传），异格式经内部 IR 双向翻译，流式和非流式都支持。

基于此派生的用户价值：

- **跨生态调用**：用 Claude Code 调 OpenAI 模型；用 OpenAI SDK 调 Claude 模型；都不改客户端代码，只改 `base_url`
- **切换上游**：同一套代码，后端在 Anthropic 原生 / OpenAI / OpenRouter / 国内中转站之间自由切换
- **集中管理**：多把 API key、多条路由规则、用量统计都在一个地方
- **零侵入**：客户端应用不需要改代码，只改 `base_url`

类比：**cc-switch 的"AI 配置管家"概念 + 自研的格式翻译引擎**。cc-switch 切的是配置文件，本项目切的是运行时流量并做格式转换。

---

## 2. 核心决策汇总

| # | 决策项 | 选择 | 备注 |
|---|---|---|---|
| 1 | 代理类型 | 应用层 API 中转 | 不是网络代理 / 反向代理 |
| 2 | 上游支持 | Anthropic 原生 + OpenAI + OpenRouter + 自定义中转 | |
| 3 | 对外 API 格式 | Claude Messages + OpenAI Chat Completions + OpenAI Responses 全部支持 | 三格式任意互译，客户端按自己习惯的接口接入 |
| 4 | 翻译引擎 | 自研核心（3×3 IR 翻译矩阵） | Responses API 较新，LiteLLM 覆盖有限；对角线直通保真，异格式走 IR |
| 5 | 本地数据库 | SQLite (aiosqlite / SQLAlchemy 2.x async) | 单用户本地场景够用 |
| 6 | Server 生命周期 | Sidecar + 引用计数（模型 ②） | GUI/CLI 任一先启动都拉起，最后一个退出带走 |
| 7 | 管理面实时性 | 普通 HTTP，不做 WebSocket | v0 不要实时流 |
| 8 | 数据面实时性 | SSE 透传 | Claude 流式响应必须 |
| 9 | 启动行为 | server 启动即开始代理 | 不搞"配置完再开"的状态机 |
| 10 | 桌面外壳 | Tauri 2.x（Rust） | 体积小、生态清爽 |
| 11 | 前端框架 | React + TypeScript + Vite + Tailwind + shadcn/ui | 主流组合 |
| 12 | 包管理（Python） | uv | 对齐团队习惯 |
| 13 | Python 打包 | PyInstaller 单文件 exe | Tauri sidecar 分发方便 |
| 14 | 平台 | Windows 优先；Tauri 支持跨平台所以将来能扩 | |

---

## 3. 架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│                              用户侧                               │
│                                                                  │
│  ┌────────────┐      ┌──────────┐      ┌────────────────────┐  │
│  │ 客户端应用  │      │ 桌面 GUI  │      │    终端 CLI          │  │
│  │ (VS Code / │      │(Tauri +   │      │  (typer)            │  │
│  │ Cursor /   │      │ React)    │      │                      │  │
│  │ 第三方程序) │      │          │      │                      │  │
│  └──────┬─────┘      └─────┬────┘      └─────────┬───────────┘  │
│         │                  │                      │              │
│  Claude 格式             管理面调用             管理面调用         │
│  业务流量                (HTTP /admin/*)        (HTTP /admin/*)   │
│  (HTTP+SSE)              (读 endpoint.json      (读 endpoint.json│
│                           拿 url+token)          拿 url+token)    │
│         │                  │                      │              │
└─────────┼──────────────────┼──────────────────────┼──────────────┘
          │                  │                      │
          ▼                  ▼                      ▼
┌──────────────────────────────────────────────────────────────────┐
│              rosetta-server （Python，FastAPI）                 │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ 数据面路由    │  │ 管理面路由    │  │  运行时              │  │
│  │ /v1/messages │  │ /admin/*     │  │  endpoint.json        │  │
│  │ /v1/models   │  │              │  │  pid lockfile         │  │
│  └──────┬───────┘  └──────┬───────┘  │  parent-watcher       │  │
│         │                 │          │  (引用计数)           │  │
│  ┌──────▼──────────────────▼──────┐  └──────────────────────┘  │
│  │      服务层 Services           │                              │
│  │  forwarder  provider_service   │                              │
│  │  router     logger   stats     │                              │
│  └──────┬────────────────────────┘                              │
│         │                                                        │
│  ┌──────▼──────────┐   ┌────────────────────────────────────┐   │
│  │ LiteLLM 翻译    │   │   SQLite (aiosqlite)               │   │
│  │ (OpenAI↔Claude) │   │   providers / keys / routes / logs │   │
│  └──────┬──────────┘   └────────────────────────────────────┘   │
│         │                                                        │
└─────────┼────────────────────────────────────────────────────────┘
          │ HTTPS
          ▼
┌──────────────────────────────────────────────────────────────────┐
│                          上游 LLM 服务                            │
│                                                                  │
│  Anthropic 原生   OpenAI   OpenRouter   国内中转站 ...            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 两条独立通道：数据面 vs 管理面

**整个系统的核心心智模型**。同一个 server 进程同时跑两套接口，用法和流量特征完全不同。

|  | **数据面（Data Plane）** | **管理面（Control Plane）** |
|---|---|---|
| 谁在用 | 你的客户端应用 | 你自己（通过 GUI / CLI） |
| 端点 | `/v1/*`（Claude + OpenAI 兼容） | `/admin/*`（内部管理） |
| 典型调用 | `POST /v1/messages` / `/v1/chat/completions` / `/v1/responses` | `GET /admin/providers`、`POST /admin/providers` |
| 流量特征 | 高频、长连接、**必须 SSE 流式** | 低频、短请求、普通 HTTP |
| 认证 | 本地 key，`x-api-key` 或 `Authorization: Bearer` 都接受 | token（从 `endpoint.json` 读） |
| 失败影响 | 客户端 AI 对话中断 | GUI 显示错误，用户手动重试 |

---

## 5. 进程模型与 sidecar 架构

### 三个进程

```
┌────────────────────────────────┐
│  Rosetta.exe (Tauri 外壳)     │
│     │                          │
│     ├── msedgewebview2.exe     │  ← 渲染 React UI
│     │                          │
│     └── rosetta-server.exe   │  ← sidecar：被 spawn
│         (PyInstaller 打包)      │     启动后绑 127.0.0.1:随机端口
└────────────────────────────────┘
         ↑
         │  同一套 server exe 也能被 CLI spawn
         │  CLI 也连它
```

### 为什么拆 sidecar

| 好处 | 说明 |
|---|---|
| **语言自由** | 外壳用 Rust 写，核心逻辑继续用 Python（复用已有 FastAPI/Pydantic 经验） |
| **可单独发布** | 同一个 `rosetta-server.exe`，单独打包就是 headless 版；和 GUI 打一起就是桌面版 |
| **崩溃隔离** | server 挂了 GUI 还能弹"连不上"，不整个白屏 |
| **多客户端共享** | CLI 和 GUI 可以连同一个 server，状态统一 |

### 打包产物

| 二进制 | 怎么来 | 内容 | 大小预估 |
|---|---|---|---|
| `rosetta-server.exe` | PyInstaller 打包 `packages/server` | FastAPI + 代理核心 + SQLite | 40–80 MB |
| `rosetta.exe`（CLI） | PyInstaller 打包 `packages/cli` | typer + 共享 SDK | 15–25 MB |
| `Rosetta.exe`（GUI） | `tauri build` + 前端 + sidecar | Rust 外壳 + WebView2 宿主 + 打包前端 + 内含 `rosetta-server.exe` | 60–100 MB |

---

## 6. Server 生命周期（模型 ②：引用计数）

### 核心原则

> **whoever needs server, checks if it's running, spawns it if not; last one out turns off the lights.**

就是 Docker 的 dockerd 模式：`docker ps` 时如果 dockerd 没跑，自动把它拉起来；所有客户端都退出后 dockerd 保持运行（Docker 里是这样；我们这里稍微改一下，最后一个客户端退出时 server 也退出，因为我们不需要像 Docker 那样服务多种后台任务）。

### endpoint.json 发现机制

Server 启动时在 `~/.rosetta/endpoint.json` 写入：

```json
{
  "url": "http://127.0.0.1:62538",
  "token": "urlsafe_random_32bytes",
  "pid": 12345
}
```

CLI 和 GUI 启动时读这个文件：
1. 不存在 → spawn server，等文件写出来（最多 5s 轮询）
2. 存在但 PID 死了 → 删掉，同上
3. 存在且 ping 通 → 复用

### 引用计数实现

Server 启动时接受 `--parent-pid <PID>` 参数。启动后开一个后台协程：

```python
async def watch_parent(pid):
    while True:
        await asyncio.sleep(3)
        if not psutil.pid_exists(pid):
            os.kill(os.getpid(), signal.SIGTERM)
            return
```

**简化**：v0 只跟踪**一个**父 PID（先启动的那个）。CLI/GUI 启动时发现 server 已存在就直接连，不注册自己为 parent。这意味着：

- **场景 A**：GUI 启动 → GUI 是 parent，关 GUI 时 server 退出。中途 CLI 能连，关 CLI server 不退。
- **场景 B**：CLI 启动 → CLI 是 parent，CLI 退出时 server 退出。中途 GUI 能连，关 GUI server 不退。

**v1 可能扩展**：让每个客户端调 `POST /admin/register-client?pid=xxx`，server 维护 PID 集合，全部死光才退出——真正的引用计数。v0 不做。

---

## 7. 项目布局（monorepo）

```
rosetta/
├── README.md
├── DESIGN.md                      # 本文档
├── .gitignore
├── .python-version
├── pyproject.toml                 # uv workspace 配置
├── uv.lock
│
└── packages/
    ├── server/                    # Python：FastAPI 代理核心 —— v0 先做这个
    │   ├── pyproject.toml
    │   ├── README.md
    │   └── rosetta_server/      # 包目录直接放在 package root，不嵌 src/
    │       ├── __init__.py
    │       ├── __main__.py        # typer CLI 入口（serve 命令）
    │       ├── main.py            # FastAPI app factory + lifespan
    │       ├── models.py          # SQLAlchemy ORM
    │       ├── api/
    │       │   ├── admin.py       # /admin/*
    │       │   └── proxy.py       # /v1/messages, /v1/chat/completions, /v1/responses, /v1/models
    │       ├── schemas/
    │       │   ├── admin.py       # 管理面 Pydantic
    │       │   ├── claude.py      # Claude Messages 请求/响应
    │       │   ├── openai_chat.py # OpenAI Chat Completions 请求/响应
    │       │   └── openai_resp.py # OpenAI Responses 请求/响应
    │       ├── services/
    │       │   ├── forwarder.py   # 总调度：选直通 or 走翻译
    │       │   ├── provider.py    # CRUD
    │       │   ├── router.py      # 路由规则（按模型/key 选 provider）
    │       │   ├── logger.py      # 请求日志落库
    │       │   └── stats.py       # 用量统计
    │       ├── translation/       # 核心翻译层
    │       │   ├── ir.py          # Request/Response/StreamEvent IR 定义
    │       │   ├── claude.py      # Claude Messages adapter（in + out + stream）
    │       │   ├── openai_chat.py # OpenAI Chat Completions adapter
    │       │   └── openai_resp.py # OpenAI Responses adapter
    │       ├── core/
    │       │   ├── config.py      # BaseSettings
    │       │   └── deps.py        # FastAPI 依赖
    │       ├── storage/
    │       │   └── db.py          # engine + session factory
    │       └── runtime/
    │           ├── endpoint.py    # 读/写 endpoint.json
    │           ├── lockfile.py    # pid-file 单例
    │           └── watcher.py     # parent pid 监控
    │
    ├── sdk/                       # Python：CLI + GUI 共用的 HTTP 客户端
    │   ├── pyproject.toml
    │   └── rosetta_sdk/
    │       ├── client.py          # 封装对 /admin/* 的所有调用
    │       ├── discover.py        # 读 endpoint.json；不存在就 spawn server
    │       └── models.py          # 和 server 共享 Pydantic 模型
    │
    ├── cli/                       # Python：终端命令行
    │   ├── pyproject.toml
    │   └── rosetta_cli/
    │       ├── __main__.py        # typer 根命令
    │       └── commands/
    │           ├── status.py      # rosetta status
    │           ├── start.py       # rosetta start（前台启动 server）
    │           ├── stop.py        # rosetta stop
    │           ├── provider.py    # rosetta provider add/list/rm
    │           ├── key.py         # rosetta key create/list/revoke
    │           └── logs.py        # rosetta logs -n 50
    │
    ├── app/                       # 前端：React + Vite
    │   ├── package.json
    │   ├── vite.config.ts
    │   ├── tailwind.config.ts
    │   ├── index.html
    │   └── src/
    │       ├── main.tsx
    │       ├── App.tsx
    │       ├── routes.tsx
    │       ├── api/               # 调后端的薄封装（OpenAPI 自动生成）
    │       ├── pages/
    │       │   ├── Dashboard.tsx  # 概览：运行状态、今日请求数、错误率
    │       │   ├── Providers.tsx  # provider 管理
    │       │   ├── Routes.tsx     # 路由规则
    │       │   ├── Keys.tsx       # 本地 key 管理
    │       │   └── Logs.tsx       # 请求日志列表（分页，无实时）
    │       └── components/        # shadcn/ui 组件
    │
    └── desktop/                   # Tauri 外壳
        ├── package.json
        ├── vite.config.ts
        ├── src-tauri/
        │   ├── Cargo.toml
        │   ├── tauri.conf.json    # 声明 externalBin = rosetta-server
        │   └── src/
        │       ├── main.rs        # 启动时 spawn server，协商端口，emit 给前端
        │       ├── sidecar.rs     # sidecar 进程管理
        │       └── lib.rs
        └── src/                   # 桌面前端入口（复用 app/）
            └── main.tsx           # 注入 Platform 实现，render app
```

---

## 8. Server 详细设计

### 8.1 API 接口清单

**管理面（供 GUI / CLI 使用）**

```
GET    /admin/ping                       健康检查，返回 {ok: true}
GET    /admin/status                     { version, uptime, provider_count, request_count, ... }

GET    /admin/providers                  列表（不返回 api_key）
POST   /admin/providers                  新建：{name, type, base_url, api_key, enabled}
GET    /admin/providers/{id}             详情
PUT    /admin/providers/{id}             修改
DELETE /admin/providers/{id}             删除
POST   /admin/providers/{id}/test        测试连通性（向上游发一个空请求）

GET    /admin/routes                     路由规则：[{model_glob, provider_id, priority}]
PUT    /admin/routes                     批量替换路由规则

GET    /admin/keys                       本地 key 列表（给客户端用的，不是 provider 的）
POST   /admin/keys                       生成新 key：{name, expires_at?}
DELETE /admin/keys/{id}

GET    /admin/logs?limit=50&offset=0     最近请求日志
GET    /admin/stats?period=today         用量统计

POST   /admin/shutdown                   优雅关停（GUI 退出时调）
```

**数据面（供客户端程序使用）**

```
POST   /v1/messages                      Claude Messages 格式
POST   /v1/chat/completions              OpenAI Chat Completions 格式
POST   /v1/responses                     OpenAI Responses 格式
                                         三者均支持：
                                           - 非流式返回 JSON（各自原生结构）
                                           - 流式返回 SSE（各自原生事件流）
GET    /v1/models                        合并所有 enabled provider 的可用模型列表
                                         返回格式按 ?format=claude|openai 决定（默认 openai）
```

鉴权头按调用方格式习惯二选一，两种都接受：
- Claude 风格：`x-api-key: <本地 key>`
- OpenAI 风格：`Authorization: Bearer <本地 key>`

Server 统一验证本地 key，不关心客户端用哪个头。

### 8.2 数据模型（SQLite 表）

```
providers
  id            INTEGER PK AUTOINCREMENT
  name          TEXT    UNIQUE NOT NULL
  type          TEXT    NOT NULL  -- anthropic / openai / openrouter / custom
  base_url      TEXT    NULLABLE  -- 为空时按 type 取默认
  api_key       TEXT    NOT NULL  -- 上游的 key
  enabled       BOOLEAN DEFAULT 1
  created_at    DATETIME

keys                                  -- 本地发出去的 key，给客户端程序用
  id            INTEGER PK
  name          TEXT    UNIQUE NOT NULL
  key           TEXT    UNIQUE NOT NULL  -- 随机字符串
  expires_at    DATETIME NULLABLE
  created_at    DATETIME
  revoked_at    DATETIME NULLABLE

routes                                -- 路由规则：按模型名选 provider
  id            INTEGER PK
  model_glob    TEXT    NOT NULL      -- e.g. "claude-*" / "gpt-4*" / "*"
  provider_id   INTEGER FK providers.id
  priority      INTEGER DEFAULT 0     -- 数字越小越优先匹配

logs                                  -- 请求流水（异步写入）
  id            INTEGER PK
  created_at    DATETIME
  key_id        INTEGER FK keys.id
  provider_id   INTEGER FK providers.id
  model         TEXT
  input_tokens  INTEGER
  output_tokens INTEGER
  latency_ms    INTEGER
  status        TEXT                  -- ok / error / timeout
  error         TEXT    NULLABLE
```

### 8.3 翻译层策略（3×3 矩阵 + IR）

**核心**：不是点对点翻译（6 条单向路径），而是 **一个统一的中间表示（IR）+ 三套 adapter**（每种格式一个 request 解析器和一个 response 生成器）。加上流/非流两种，实际代码分摊比 6 条硬写的 glue 少得多。

#### 翻译矩阵

客户端格式（行） × 上游格式（列）：

| | → Claude Messages | → OpenAI Chat | → OpenAI Responses |
|---|---|---|---|
| **Claude Messages** | 直通（httpx） | C → IR → OC | C → IR → OR |
| **OpenAI Chat** | OC → IR → C | 直通（httpx） | OC → IR → OR |
| **OpenAI Responses** | OR → IR → C | OR → IR → OC | 直通（httpx） |

对角线三格**直通**，httpx 原样转发 request + SSE 流，保真、零翻译风险。其余 6 格走 IR。

#### 中间表示（IR）

IR 只对齐三格式的**公共语义**，不追求 1:1 还原每个字段：

```
Request IR:
  model, system, messages[], tools[], tool_choice,
  sampling(temperature, top_p, max_tokens, stop), stream,
  _extras{}  # 无法映射的原字段保留，回写时尽量恢复

Message:
  role (user/assistant/tool),
  content: [TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock]

Response IR:
  id, model, content[], stop_reason, usage{input_tokens, output_tokens}

Stream Event IR:
  MessageStart / ContentBlockStart / ContentBlockDelta
  ContentBlockStop / MessageDelta / MessageStop
  （以 Claude 的事件粒度为 IR 基准，因为它最细）
```

#### 请求方向（client → upstream）

```
客户端 JSON
  → [inbound adapter] 解析到 IR
  → [router] 按 IR.model 选 provider
  → [outbound adapter] IR 序列化为上游格式
  → httpx 发上游
```

#### 响应方向（upstream → client）

**非流式**：上游 JSON → 上游 adapter 解析到 Response IR → 客户端 adapter 序列化回客户端格式。

**流式**：逐事件翻译，不能聚合等全部完成（否则失去流式体验）：

```
上游 SSE 事件
  → [upstream stream adapter] 增量填入 Stream Event IR
  → [client stream adapter] 从 IR 事件转成客户端 SSE
  → 立刻 yield 给客户端
```

每个 adapter 内部维护一点状态机（追踪当前 content block index、tool call id 映射等），因为三种格式的流式粒度不同：Claude 按 content block 分事件，Chat Completions 只有 `delta`，Responses 事件种类最多（`response.output_text.delta` / `response.function_call.arguments.delta` 等）。

#### 关键字段对照

| 语义 | Claude Messages | OpenAI Chat Completions | OpenAI Responses |
|---|---|---|---|
| 系统消息 | 顶层 `system` | `messages[role=system]` | 顶层 `instructions` |
| 助手输出 | `content[]` blocks | `choices[0].message.content` + `tool_calls` | `output[]` items |
| 工具定义 | `tools[{name, input_schema}]` | `tools[{type:function, function:{...}}]` | `tools[]`（含内置 tool type） |
| 工具调用 | `content[]` 内 `tool_use` block | `message.tool_calls[]` | `output[]` 内 `function_call` |
| 工具结果 | user 消息的 `tool_result` block | `role: tool` 独立 message | `input[]` 内 `function_call_output` |
| 停止原因 | `stop_reason` (`end_turn`/`tool_use`/...) | `finish_reason` (`stop`/`tool_calls`/...) | `status` + `incomplete_details` |
| 流式文本增量 | `content_block_delta.delta.text` | `choices[0].delta.content` | `response.output_text.delta` |
| 流式工具增量 | `content_block_delta.delta.partial_json` | `choices[0].delta.tool_calls[].function.arguments` | `response.function_call_arguments.delta` |
| Token 用量 | `usage.{input,output}_tokens` | `usage.{prompt,completion}_tokens` | `usage.{input,output}_tokens` |

#### Responses API 有状态特性（v0 策略）

Responses API 相比 Chat Completions 多了会话状态能力，翻译时需要降级：

| 特性 | Responses→Responses 直通 | 翻到 Chat 或 Claude |
|---|---|---|
| `store=true` / stored responses | 保留 | 忽略（日志 warning） |
| `previous_response_id` | 保留 | v0 报 400（客户端需自己维护上下文） |
| `background: true` | 保留 | v0 报 400 |
| 内置 tools（`web_search`/`code_interpreter`/`file_search`） | 保留 | 剔除并返回 header `x-rosetta-warnings` |

#### 实施优先级

- **v0.1**：Claude ↔ Chat Completions 双向（覆盖绝大多数现有客户端+上游组合）
- **v0.2**：加入 Responses API 的 in/out 两侧
- **同格式直通**：三条对角线 day-0 就通，不依赖翻译器

### 8.4 路由规则

请求来时按这个顺序匹配：

```
1. 取请求的 model 字段，e.g. "claude-sonnet-4-5"
2. 按 priority ASC 遍历 routes 表
3. 第一个 model_glob 匹配的 → 用那条的 provider_id
4. 都不匹配 → 用第一个 enabled 的 provider
5. 该 provider 被禁用 / 不存在 → 503
```

默认规则示例：

```
priority=1  model_glob="claude-*"  provider=anthropic
priority=2  model_glob="gpt-*"     provider=openai
priority=9  model_glob="*"         provider=openrouter  (fallback)
```

### 8.5 本地 key

用户创建的 key 交给客户端程序使用，和上游 provider 的 key **完全分开**。好处：

- 客户端不碰你真的 Anthropic/OpenAI key
- 一把本地 key 泄露只需要 `DELETE /admin/keys/{id}` 撤销
- 多客户端（VS Code / Cursor / 脚本）各发一把，方便审计用量

格式：`rs_xxxxxxxxxxxxxxxxxxxxxxxxxx`（前缀 `rs_`, 便于识别）。

---

## 9. SDK 设计（`packages/sdk`）

CLI 和 GUI 都不直接调 HTTP，而是通过 SDK：

```python
# sdk/client.py
from rosetta_sdk import ProxyClient

async with ProxyClient.discover() as client:
    # .discover() 内部：
    # 1. 读 endpoint.json
    # 2. 不存在/死了 → spawn server
    # 3. 等 ready（轮询 /admin/ping）
    # 4. 拿 url + token 建 httpx.AsyncClient
    status = await client.status()
    providers = await client.list_providers()
    await client.create_provider(name="...", type="anthropic", api_key="...")
```

Pydantic 模型从 `packages/server/src/rosetta_server/schemas/` **复用**（monorepo 内部依赖），**不手写第二份**。

---

## 10. CLI 设计（`packages/cli`）

```bash
# server 管理
rosetta start              # 后台启动 server（守护模式，立即返回）
rosetta stop               # 优雅关停
rosetta status             # 状态概览
rosetta serve              # 前台启动（开发调试用，同 rosetta-server serve）

# provider 管理
rosetta provider list
rosetta provider add --name foo --type anthropic --api-key sk-ant-...
rosetta provider remove foo
rosetta provider test foo

# key 管理
rosetta key list
rosetta key create --name "cursor-use"
rosetta key revoke rs_xxxxxxxxxxxx

# 观测
rosetta logs -n 50
rosetta stats today
```

---

## 11. GUI 设计（`packages/app` + `packages/desktop`）

### 页面清单（v0 功能）

1. **Dashboard** — 状态、今日请求数、错误率、在跑的 provider 列表
2. **Providers** — 表格 + 新增/编辑 Modal（shadcn/ui 的 Dialog + Form）
3. **Routes** — 路由规则拖拽排序（可选 v1）
4. **Keys** — 本地 key 的创建/撤销
5. **Logs** — 请求列表 + 按 key / provider / 时间筛选

### Tauri 侧职责（Rust，`packages/desktop/src-tauri`）

- 启动时 spawn `rosetta-server.exe` 作为 sidecar，传 `--parent-pid`
- 把协商好的 URL + token emit 给前端
- 窗口状态记忆（`tauri-plugin-window-state`）
- 系统托盘 + 最小化到托盘
- 自动更新（`tauri-plugin-updater`）

### 前端 Platform 抽象（学 opencode）

```ts
interface Platform {
  getBackendUrl(): string
  getBackendToken(): string
  openExternalLink(url: string): void
  quit(): void
}
```

- Tauri 实现：走 `@tauri-apps/api`
- Web 版实现（如果做 Web UI）：走原生 `fetch` + `window.open`

这样 `packages/app` 的 React 代码不耦合 Tauri。

---

## 12. 部署与打包

### 开发

```bash
# 装依赖
uv sync

# 启 server（dev 模式，reload）
cd packages/server
uv run uvicorn rosetta_server.main:app_factory --factory --reload

# 启前端 dev server
cd packages/app
pnpm install
pnpm dev

# 启 Tauri 开发（会拉起前端 dev server + sidecar）
cd packages/desktop
pnpm tauri dev
```

### 打包分发

```bash
# 1. 打包 server 成单 exe
cd packages/server
uv run pyinstaller --onefile --name rosetta-server \
  --hidden-import aiosqlite \
  src/rosetta_server/__main__.py
#   产物：dist/rosetta-server.exe

# 2. 打包 CLI
cd packages/cli
uv run pyinstaller --onefile --name rosetta src/rosetta_cli/__main__.py

# 3. 桌面打包（自动把 server exe 打进安装包）
cd packages/desktop
# tauri.conf.json 里声明：
#   "bundle": {
#     "externalBin": ["binaries/rosetta-server"]
#   }
# 产物：Rosetta-setup.exe
pnpm tauri build
```

---

## 13. 分阶段实施路线图

```
阶段 1（1-2 天）  packages/server 骨架 + 三格式直通
  ✅ FastAPI app + /admin/ping + /admin/status
  ✅ Provider CRUD（仅 GET/POST）
  ✅ /v1/messages、/v1/chat/completions、/v1/responses 三条入口
  ✅ 同格式直通（httpx 透传流 + 非流）
  ✅ endpoint.json + pid lockfile
  验收：三种格式各自用原生 SDK 调本地代理→对应上游，响应和直连一致

阶段 2（3-5 天）  翻译层 v0.1（Claude ↔ Chat Completions）
  ✅ IR 定义 + Claude adapter + OpenAI Chat adapter
  ✅ 非流式双向翻译
  ✅ 流式事件双向翻译（状态机 + 逐事件 yield）
  ✅ 工具调用（tool_use ↔ tool_calls）双向翻译
  验收：用 Claude SDK 成功调用 OpenAI 模型；用 OpenAI SDK 成功调用 Claude 模型；流式和 tools 都正确

阶段 2.5（2-3 天）翻译层 v0.2（加入 Responses API）
  ✅ OpenAI Responses adapter
  ✅ Responses ↔ Claude、Responses ↔ Chat 双向翻译
  ✅ 有状态特性降级策略（store / previous_response_id / 内置 tools）
  验收：三格式两两互通的 6 条翻译路径 + 3 条直通都走得通

阶段 3（1 天）    本地 key + 路由规则
  ✅ keys 表 + CRUD
  ✅ routes 表 + 匹配逻辑
  ✅ 数据面入口鉴权（x-api-key 和 Authorization 都接受）
  验收：创建多个 provider，按模型名自动路由

阶段 4（半天）    packages/sdk + packages/cli 基础命令
  ✅ discover + client
  ✅ CLI 四大命令：status / start / stop / provider list
  验收：`rosetta status` 能跑通全链路

阶段 5（2-3 天）  packages/app 前端
  ✅ Vite + React + Tailwind + shadcn/ui 脚手架
  ✅ Dashboard / Providers / Keys 三个页面
  ✅ 直接连本地 server 开发（不经 Tauri）
  验收：浏览器里能增删 provider、看状态

阶段 6（1 天）    PyInstaller 打包 + CI
  ✅ server 和 CLI 打出单 exe
  ✅ 验证单独运行 OK
  验收：双击 rosetta-server.exe 能启动

阶段 7（2-3 天）  packages/desktop Tauri 外壳
  ✅ spawn sidecar + 协商端口 + emit 给前端
  ✅ 窗口记忆 + 托盘
  ✅ Platform 抽象
  验收：`tauri dev` 启动桌面端，和浏览器里表现一致

阶段 8（1-2 天）  打磨与发布
  ✅ 日志 / stats 页面
  ✅ 错误态 UI
  ✅ 自动更新（tauri-plugin-updater）
  ✅ 代码签名 + 安装包
  验收：Rosetta-setup.exe 安装运行一切正常

────────────────
  后续（v1）
  ✅ 翻译层健壮性打磨（多模态 / 罕见 tool_choice 组合 / 边缘字段）
  ✅ 实时日志流（WebSocket）
  ✅ Provider PUT/DELETE + test
  ✅ 路由规则拖拽排序
  ✅ 多语言（i18n）
  ✅ 跨平台打包（mac/linux）
```

**总预估：** 阶段 1–8 约 15–20 人日（熟练开发）。新增的翻译层（阶段 2 + 2.5）是主要工作量来源。

---

## 14. 风险与待决议项

### 已识别的风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **自研翻译层边缘 case** | 多模态 / 罕见 tool_choice 组合 / 特殊 stop_reason 翻译不准 | 金标样本集 + 每条路径 E2E 测试；无法翻译的字段落入 `_extras` 保留；非关键字段丢失返回 warning 头 |
| **流式状态机 bug** | SSE 翻译错位导致客户端 SDK 解析失败 | 翻译器用状态机明确转移图；对每个 adapter 写 fixture-based 流式回归测试 |
| **Responses API 有状态特性** | 翻译到 Chat/Claude 时丢失会话上下文 | 明确降级策略（§8.3），客户端发 `previous_response_id` 且上游非 Responses 时直接 400 |
| **上游 API 版本漂移** | 上游字段增删导致透传或翻译失败 | 直通路径只检必要字段；翻译路径的未知字段进 `_extras` 回传 |
| **PyInstaller 打包体积大** | 用户下载慢 | 可接受（40-80MB），后续考虑 Nuitka |
| **SSE 透传的超时和取消** | 客户端断开时不释放上游连接 | httpx.stream + `async for` 会正确传播取消 |
| **SQLite 并发写** | 高 QPS 时锁冲突 | 异步写请求日志通过内存 queue + 批量 flush |
| **Windows 下子进程 kill** | 父进程崩溃时 sidecar 变僵尸 | Tauri 用 JobObject；Python 的 watcher.py 做保底 |

### 待决议

- [ ] **GUI 主题色/品牌**：随 shadcn 默认，或做定制？
- [ ] **是否需要用户账户系统**：v0 假设单用户本地；多用户（多台机器共享一个 server）是否考虑？
- [ ] **配置文件导入导出**：是否支持 `rosetta config export/import`？便于多机同步
- [ ] **观察指标粒度**：stats 是否需要按 model/key 分别统计？
- [ ] **日志保留时长**：logs 表无限增长问题，何时 TTL 清理？

---

## 15. 参考资料

- [opencode 架构分析](../claude_test/opencode.md) — 同款 sidecar + Tauri 模式，可参考其 Platform 抽象和三层分包
- cc-switch（https://github.com/farion1231/cc-switch）— 同类产品，UI/交互可参考
- [LiteLLM 文档](https://docs.litellm.ai/) — 翻译层核心依赖
- [Tauri 2.x externalBin/sidecar](https://v2.tauri.app/develop/sidecar/)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)

---

_本文档是实施前的唯一信息源。有改动请在此文档更新后再动代码。_
