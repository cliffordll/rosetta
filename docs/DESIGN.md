# rosetta 设计方案

> 版本：v0.1 · 起草日期：2026-04-20
> 状态：设计评审中，未开始实现
> 本文档**只描述架构**。分阶段实施计划见 [`FEATURE.md`](./FEATURE.md)(heading emoji 标进度);执行细节由 commit history 承载。

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
| 5 | 本地数据库 | SQLite (SQLAlchemy 2.x async，aiosqlite 作底层驱动) | 单用户本地场景够用 |
| 6 | Server 生命周期 | Sidecar + 引用计数（模型 ②） | GUI/CLI 任一先启动都拉起，最后一个退出带走 |
| 7 | 管理面实时性 | 普通 HTTP，不做 WebSocket | v0 不要实时流 |
| 8 | 数据面实时性 | SSE 透传 | Claude 流式响应必须 |
| 9 | 启动行为 | server 启动即开始代理 | 不搞"配置完再开"的状态机 |
| 10 | 桌面外壳 | Tauri 2.x（Rust） | 体积小、生态清爽 |
| 11 | 前端框架 | React + TypeScript + Vite + Tailwind + shadcn/ui | 主流组合 |
| 12 | 包管理（Python） | uv | 对齐团队习惯 |
| 13 | Python 打包 | PyInstaller 单文件 exe | Tauri sidecar 分发方便 |
| 14 | 平台 | Windows 优先；Tauri 支持跨平台所以将来能扩 | |
| 15 | 鉴权模型 | server 只绑 `127.0.0.1` / `::1`，无 API-level auth；客户端 `x-api-key` 头直接透传给上游 | 不引入 rosetta 自有的"本地 key"层；单用户本地场景靠 loopback 隔离；暴露公网请挂反代自加 auth |

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
│  三格式业务流量          管理面调用             管理面调用         │
│  (/v1/messages 或       (HTTP /admin/*)        (HTTP /admin/*)   │
│   chat/completions 或    (读 endpoint.json      (读 endpoint.json│
│   responses, +SSE)       拿 url+token)          拿 url+token)    │
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
│  │  forwarder  upstream           │                              │
│  │  selector   logger   stats     │                              │
│  └──────┬────────────────────────┘                              │
│         │                                                        │
│  ┌──────▼──────────┐   ┌────────────────────────────────────┐   │
│  │ Translation 3×3 │   │   SQLite (SQLAlchemy + aiosqlite)  │   │
│  │ IR + 3 adapters │   │   upstreams / logs                 │   │
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
| 典型调用 | `POST /v1/messages` / `/v1/chat/completions` / `/v1/responses` | `GET /admin/upstreams`、`POST /admin/upstreams` |
| 流量特征 | 高频、长连接、**必须 SSE 流式** | 低频、短请求、普通 HTTP |
| 认证 | **无 API-level auth**（loopback-only 隔离）；`x-api-key` / `Authorization: Bearer` 若传则透传给上游作 override，不传用 `upstreams.api_key` | token（从 `endpoint.json` 读，仅防跨用户误触） |
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
| `rosetta-server.exe` | PyInstaller 以 `rosetta/server/__main__.py` 为入口打包 | FastAPI + 代理核心 + SQLite | 40–80 MB |
| `rosetta.exe`（CLI） | PyInstaller 以 `rosetta/cli/__main__.py` 为入口打包 | typer + SDK 子包 | 15–25 MB |
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

**并发 spawn 保护**：CLI 和 GUI 同时启动时可能都读到"文件不在"，需要避免双 spawn。约定：

- Server 启动第一步用 `O_CREAT | O_EXCL` 在 `~/.rosetta/spawn.lock` 抢占独占句柄（文件内容=本进程 PID），拿不到锁就直接退出(exit 0)。
- 客户端侧 spawn 前也先尝试拿同一把锁：拿到 → 自己 spawn；拿不到 → 说明别人在 spawn，转为"轮询 `endpoint.json`"最多 5s。
- Server 绑端口、写完 `endpoint.json` 之后立刻释放 `spawn.lock`。`endpoint.json` 本身的写入用"写到 `.tmp` → `rename` 原子替换"，避免客户端读到半截文件。
- 启动失败 / 崩溃不释放 lock 的情况：文件里的 PID 不存在 → 客户端当作陈旧锁删掉重试。

### 引用计数实现

Server 启动时接受 `--parent-pid <PID>` 参数。启动后开一个后台协程：

```python
async def watch_parent(pid, app_state):
    while True:
        await asyncio.sleep(3)
        if not psutil.pid_exists(pid):
            # 父进程死了：不立即 SIGTERM，先等进行中的 /v1/* 请求收尾
            await graceful_shutdown(app_state)
            os.kill(os.getpid(), signal.SIGTERM)
            return
```

**优雅关闭约定**（`graceful_shutdown`）：

1. 停止 accept 新连接（Uvicorn `server.should_exit = True`）
2. 等当前进行中的 `/v1/*` 请求（含 SSE 流）跑完，上限 30s
3. 超时未结束的连接：关 TCP，客户端会看到断流（靠它自己的重试）
4. flush `logs` 写入队列
5. 删除 `endpoint.json`（最后一步，在此之前其他客户端仍可能读到有效文件）

**简化**：v0 只跟踪**一个**父 PID（先启动的那个）。CLI/GUI 启动时发现 server 已存在就直接连，不注册自己为 parent。这意味着：

- **场景 A**：GUI 启动 → GUI 是 parent，关 GUI 时 server 退出。中途 CLI 能连，关 CLI server 不退。
- **场景 B**：CLI 启动 → CLI 是 parent，CLI 退出时 server 退出。中途 GUI 能连，关 GUI server 不退。

**v1 可能扩展**：让每个客户端调 `POST /admin/register-client?pid=xxx`，server 维护 PID 集合，全部死光才退出——真正的引用计数。v0 不做。

---

## 7. 项目布局（monorepo）

Python 侧采用**单包 + 子包**结构：一份 `pyproject.toml`，整个 Python 代码库是一个 `rosetta` 包，内部按功能划分 `server/` / `sdk/` / `cli/` 三个子包。JS / Rust 产物放在 `packages/` 下由 bun workspace 管理。

```
rosetta/
├── README.md                     # 项目简介（留根，GitHub 默认渲染）
├── docs/                         # 设计与路线图文档集中在此
│   ├── DESIGN.md                 # 本文档（架构设计 · 真源）
│   ├── FEATURE.md                # 分步开发任务清单（可验收 + v1+ 规划 · heading emoji 标进度）
│   └── archive/                  # 已归档备选方案（不再维护）
│       ├── DESIGN_TS.md          # TS 栈备选
│       ├── DESIGN_multi_pkg.md   # 旧三包布局备份
│       └── PROCESS.md            # 早期执行进度日志(已停写,由 commit history 承载)
├── .gitignore
├── .python-version
├── pyproject.toml                # Python 包 rosetta 的定义（依赖 / entry points / 工具配置）
├── uv.lock
├── package.json                  # bun workspace 根（声明 app、desktop 成员）
├── bun.lockb
│
├── rosetta/                    # ← Python 源码，扁平放在 repo 根
│   ├── __init__.py
│   ├── shared/                   # 跨子包共用
│   │   ├── __init__.py
│   │   └── formats.py            # ▣ NEW  三格式标识 messages/completions/responses + URL 路径映射
│   │                             #         + 内置默认模型表（type → 最便宜 smoke 模型）
│   │
│   ├── server/                   # 子包：FastAPI 代理核心 —— v0 先做这个
│   │   ├── __init__.py
│   │   ├── __main__.py           # python -m rosetta.server → 启动 server
│   │   ├── app.py                # FastAPI app factory + lifespan
│   │   │
│   │   ├── controller/           # HTTP 层：所有 endpoint + 错误映射
│   │   │   ├── __init__.py       # admin_router + dataplane_router 聚合 + register_exception_handlers
│   │   │   ├── runtime.py        # /admin/ping、/admin/status、/admin/shutdown
│   │   │   ├── upstreams.py      # /admin/upstreams CRUD（UpstreamCreate / UpstreamOut 内联）
│   │   │   ├── logs.py           # GET /admin/logs
│   │   │   ├── stats.py          # GET /admin/stats
│   │   │   ├── dataplane.py      # POST /v1/messages、/v1/chat/completions、/v1/responses
│   │   │   └── errors.py         # rosetta_error(code, message, **extra) 错误响应体工厂
│   │   │
│   │   ├── service/              # business logic 层：不依赖 HTTP / FastAPI
│   │   │   ├── __init__.py
│   │   │   ├── forwarder.py      # Forwarder 类 + 模块级单例；httpx 转发 + 翻译编排 + SSE 透传
│   │   │   ├── selector.py       # pick_upstream：按 x-rosetta-upstream header 选 upstream
│   │   │   └── exceptions.py     # ServiceError(status, code, message, **extra) domain exception
│   │   │
│   │   ├── repository/           # data access 层：ORM 查询封装
│   │   │   ├── __init__.py       # re-export + UpstreamRepoDep / LogRepoDep FastAPI 依赖别名
│   │   │   ├── upstream.py       # UpstreamRepo(list_all / get_by_id / get_by_name / count / create / delete)
│   │   │   └── log.py            # LogRepo(list_with_upstream / aggregate_stats)
│   │   │
│   │   ├── database/             # infra：engine / session / models / migrations
│   │   │   ├── __init__.py
│   │   │   ├── models.py         # SQLAlchemy 2.x 声明式 Base + Upstream / LogEntry
│   │   │   ├── session.py        # async engine + session_maker + init_db/dispose_db + migration runner + SessionDep
│   │   │   └── migrations/
│   │   │       ├── __init__.py
│   │   │       ├── 001_init.sql  # 两表 DDL + idx_logs_created_at + PRAGMA user_version=1
│   │   │       └── 002_drop_routes.sql  # DROP TABLE IF EXISTS routes + user_version=2（2026-04 简化）
│   │   │
│   │   ├── translation/          # 纯工具：跨格式翻译（无状态，可独立测试）
│   │   │   ├── __init__.py
│   │   │   ├── ir.py             # Request/Response/StreamEvent IR 定义
│   │   │   ├── dispatcher.py     # translate_request / translate_response / translate_stream_* 分派
│   │   │   ├── sse.py            # parse_sse_stream / encode_sse_stream（SSE 协议编解码）
│   │   │   ├── degradation.py    # Responses → 非 Responses 的降级预处理
│   │   │   ├── messages/         # Protocol.MESSAGES（Anthropic Messages API）
│   │   │   │   ├── request.py    # messages_to_ir / ir_to_messages
│   │   │   │   └── response.py   # 非流式 + 流式（content_block_* 状态机）
│   │   │   ├── completions/      # Protocol.CHAT_COMPLETIONS（OpenAI Chat Completions）
│   │   │   │   ├── request.py
│   │   │   │   └── response.py
│   │   │   └── responses/        # Protocol.RESPONSES（OpenAI Responses）
│   │   │       ├── request.py
│   │   │       └── response.py
│   │   │
│   │   └── runtime/              # ⊕ 扩 进程生命周期管理（阶段 1.4）
│   │       ├── endpoint.py       # 读/写 endpoint.json（.tmp → rename 原子替换）
│   │       ├── lockfile.py       # spawn.lock 独占创建 + PID 陈旧检测
│   │       └── watcher.py        # parent PID 监控 + 5 步优雅关闭
│   │
│   ├── sdk/                      # 子包：HTTP 客户端（CLI 用；导出给外部脚本复用）
│   │   ├── __init__.py
│   │   ├── client.py             # 封装 /admin/* 的所有调用
│   │   ├── discover.py           # 读 endpoint.json；不存在就 spawn server
│   │   ├── chat.py               # ▣ NEW  chat_once() —— 发一条消息，返回 ChatResult
│   │   │                         #         （text / usage / path / latency / raw_response）
│   │   │                         #         direct 模式也在这里分派：有 --base-url 就绕 server
│   │   └── streams.py            # ▣ NEW  iter_text_deltas(response, format) —— 三格式 SSE → 文本增量
│   │
│   └── cli/                      # 子包：终端命令行
│       ├── __init__.py
│       ├── __main__.py           # python -m rosetta.cli → typer 根命令
│       ├── repl.py               # ▣ NEW  Chat REPL 循环与状态机（/exit /reset /model /format）
│       ├── render.py             # ▣ NEW  终端渲染工具：流式 token 打印、meta 行、错误气泡
│       └── commands/
│           ├── status.py         # rosetta status
│           ├── start.py          # rosetta start
│           ├── stop.py           # rosetta stop
│           ├── serve.py          # rosetta serve（前台，调试）
│           ├── upstream.py       # rosetta upstream add/list/remove
│           ├── logs.py           # rosetta logs -n 50
│           ├── stats.py          # ▣ NEW  rosetta stats today/week/month
│           └── chat.py           # ▣ NEW  rosetta chat —— 一次性模式 + REPL 模式分发
│
├── tests/                        # Python 测试（pytest）
│   ├── server/
│   ├── sdk/
│   │   └── test_streams.py       # ▣ NEW  三格式 SSE 解码金标
│   ├── cli/
│   │   └── test_chat.py          # ▣ NEW  一次性 + REPL（mock SDK）
│   └── translation/              # 翻译层金标样本
│
└── packages/                     # 非 Python 工作区成员
    ├── app/                      # 前端：React + Vite
    │   ├── package.json
    │   ├── vite.config.ts
    │   ├── tailwind.config.ts
    │   ├── index.html
    │   └── src/
    │       ├── main.tsx
    │       ├── App.tsx
    │       ├── routes.tsx
    │       ├── api/              # /admin/* 薄封装（OpenAPI 自动生成）—— 调管理面
    │       ├── services/         # ▣ NEW  数据面客户端 —— 调 /v1/*
    │       │   ├── chat.ts        # fetch + AbortController + 可选 override api-key 头注入
    │       │   │                  #   + Message/ChatResult/Format 类型
    │       │   └── chatStreams.ts # 三格式 SSE 解码（TS 版，对照 Python sdk/streams.py）
    │       ├── pages/
    │       │   ├── Dashboard.tsx
    │       │   ├── Upstreams.tsx
    │       │   ├── Logs.tsx
    │       │   └── Chat.tsx      # ▣ NEW  Chat 页主组件（messages state + 三下拉 + 发送）
    │       └── components/
    │           ├── ...（原有 shadcn/ui 组件）
    │           └── chat/         # ▣ NEW  Chat 页专用组件
    │               ├── MessageBubble.tsx
    │               ├── ChatInput.tsx
    │               ├── MetaLine.tsx
    │               └── ErrorBubble.tsx
    │
    └── desktop/                  # Tauri 外壳（无变化）
        ├── package.json
        ├── vite.config.ts
        ├── src-tauri/
        │   ├── Cargo.toml
        │   ├── tauri.conf.json   # 声明 externalBin = rosetta-server
        │   └── src/
        │       ├── main.rs       # spawn server，协商端口，emit 给前端
        │       ├── sidecar.rs
        │       └── lib.rs
        └── src/
            └── main.tsx          # 注入 Platform 实现，render app
```

图例：**▣ NEW** = 本轮新增；**⊕ 扩** = 在已有文件上加功能。


### 与"三包"旧方案的差异

之前的方案是 `packages/server` / `packages/sdk` / `packages/cli` 三个独立 Python 包，各自带 `pyproject.toml`。新方案合并成单包后：

| 点 | 旧方案（三包） | 新方案（单包 + 子包） |
|---|---|---|
| `pyproject.toml` 数量 | 3 份 | 1 份 |
| 子包互相 import | `from rosetta_server.schemas.admin import ...` | `from rosetta.server.schemas.admin import ...` |
| sdk / cli 复用 server 的 Pydantic | 需要 server 包 export，sdk 声明依赖 | 同包内直接 import，无需声明 |
| 独立版本号 | 支持（实际用不上） | 不支持（三子包共用一个版本） |
| 到代码层数（从 repo 根） | 3（`packages/server/rosetta_server/main.py`） | 2（`rosetta/server/main.py`） |
| exe 打包入口 | `packages/server/rosetta_server/__main__.py` | `rosetta/server/__main__.py` |

备份在 `archive/DESIGN_multi_pkg.md`，需要回退时直接覆盖本文件即可。

---

## 8. Server 详细设计

### 8.1 API 接口清单

**管理面（供 GUI / CLI 使用）**

```
GET    /admin/ping                       健康检查，返回 {ok: true}
GET    /admin/status                     { version, uptime, upstream_count, request_count, ... }

GET    /admin/upstreams                  列表（不返回 api_key）
POST   /admin/upstreams                  新建：{name, type, base_url, api_key, enabled}
GET    /admin/upstreams/{id}             详情
PUT    /admin/upstreams/{id}             修改
DELETE /admin/upstreams/{id}             删除
（连通性测试端点 `POST /admin/upstreams/{id}/test` 推迟到 v1+，见 `FEATURE.md` 附录 B）

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
GET    /v1/models                        合并所有 enabled upstream 的可用模型列表
                                         返回格式按 ?format=messages|completions 决定（默认 completions）
                                         （只有两种 shape：messages=Claude 风格，completions=OpenAI 风格；
                                           Responses API 的 models 列表用 OpenAI shape，调用方传 format=completions 即可）
                                         可选过滤：?upstream=<name> 只返回该 upstream 的模型
                                         响应中每条 model 额外带 "upstream": "<name>" 字段，方便前端自行按 upstream 分组过滤
```

**鉴权与 api-key 透传规则**：

- server **不做 API-level 鉴权**，只绑 loopback（`127.0.0.1` / `::1`），非本机请求在 TCP 层就拒绝
- 数据面（`/v1/*`）的 `x-api-key` / `Authorization: Bearer` **不是用来验 rosetta 身份的**，它是**上游 key 的透传槽**：
  - 客户端请求里**带了**鉴权头 → server 把这把 key 写到发给上游的请求头里（按上游 type 选 `x-api-key` 还是 `Authorization: Bearer` 的写法）
  - 客户端请求里**没带** → fallback 到 `upstreams.api_key`（DB 里预先配置的那一把）
- 管理面（`/admin/*`）的 token 仍从 `endpoint.json` 读，仅作跨用户误触防护（同机不同 user 别乱连），不是安全边界

**数据面必需 header(仅对 `/v1/*` 生效)**:

- `x-rosetta-upstream: <name>` — **必须**指定上游 upstream(按 name 精确匹配)。缺失 / upstream 不存在 / disabled 都返回 400。rosetta 不做 model-based 自动路由,客户端需自行选 upstream(CLI `rosetta chat --upstream`、Chat 页、外部 SDK 都统一靠这个 header)。

### 8.2 数据模型（SQLite 表）

```
upstreams
  id            INTEGER PK AUTOINCREMENT
  name          TEXT    UNIQUE NOT NULL
  protocol      TEXT    NOT NULL  -- messages / completions / responses
  base_url      TEXT    NULLABLE  -- 为空时按 type 取默认
  api_key       TEXT    NOT NULL  -- 上游的 key
  enabled       BOOLEAN DEFAULT 1
  created_at    DATETIME

logs                                  -- 请求流水（异步写入）
  id            INTEGER PK
  created_at    DATETIME
  upstream_id   INTEGER FK upstreams.id
  model         TEXT
  input_tokens  INTEGER
  output_tokens INTEGER
  latency_ms    INTEGER
  status        TEXT                  -- ok / error / timeout
  error         TEXT    NULLABLE
  -- 不记录 api_key（即使哈希）：单用户本地无审计需求，v1+ 真有需要再加

  INDEX idx_logs_created_at (created_at)  -- 为 TTL 清理和时间段查询建索引
```

**Schema 版本与迁移**：

- 建库时 `PRAGMA user_version = N`（N 随 schema 变更递增，v0.1 起为 1）
- Server 启动时读 `PRAGMA user_version`：
  - 等于当前版本 → 正常启动
  - 小于当前版本 → 按顺序跑 `migrations/NNN_*.sql`，跑完更新 user_version
  - 大于当前版本（老 server 开新 DB）→ 拒绝启动，日志提示"DB schema 来自更高版本 rosetta"
- 迁移脚本放 `rosetta/server/database/migrations/`，文件名 `001_init.sql` / `002_add_xxx.sql`

**实现约定**（阶段 1.2 落地,修订见 commit history):

- migration runner 走 SQLAlchemy `engine.begin()` 事务，**代码里不 import aiosqlite**（aiosqlite 仅作为 SQLAlchemy 的底层驱动被动加载）
- 启动时自检 `CURRENT_SCHEMA_VERSION == max(migrations[*].N)`，不一致拒启动（防止常量改了忘加 SQL 文件，或反之）
- 每个 migration 在**独立事务**里跑，任一失败不回滚已成功的前几个
- migration 目录通过 glob `[0-9][0-9][0-9]_*.sql` 扫描，按编号升序；编号重复启动时报错

（v0 **不再有 `keys` 表**——rosetta 自己的"本地 key"概念已删除。`upstreams.api_key` 是上游 key 的默认值，客户端可通过 `x-api-key` 头逐次 override。）

**`upstreams.base_url` 默认值**（type 对应的官方上游，建 upstream 时 `base_url` 留空就取这里）：

| type | base_url 为空时使用 | 典型用途 |
|---|---|---|
| `anthropic` | `https://api.anthropic.com` | 直连 Anthropic |
| `openai` | `https://api.openai.com` | 直连 OpenAI |
| `openrouter` | `https://openrouter.ai/api` | 经 OpenRouter 多供应商 |
| `custom` | **必须显式填写**，否则 `POST /admin/upstreams` 返回 400 | 国内中转站、自托管 vLLM / Ollama、第三方网关 |

填写自定义 `base_url`（如 `https://api.deepseek.com/anthropic`）会覆盖默认；**不带尾斜杠、不带 `/v1`**——forwarder 自动拼路径。

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
  → [selector] 按 x-rosetta-upstream header 选 upstream
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

**流式错误传播**：一旦上游返回 200 + `text/event-stream`，HTTP 状态码已不可变。规则：

- 上游在流中发出错误事件（Claude `event: error` / OpenAI SSE error 帧）→ 翻译成客户端格式的对应错误事件原样透传，继续保持 200
- 上游 TCP 断开 / 超时 / 抛异常 → server 关闭给客户端的 TCP 连接，不补发任何伪造事件（客户端靠自己的 SSE 重试逻辑）
- server 本身异常（翻译器 panic 等）→ 若已 yield 过数据:关连接;若尚未 yield:走正常 5xx 响应
- 所有这些情况都写 `logs.status = error` 并尽量记 `error` 文本

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

**rosetta 不做 model-based 自动路由**,客户端必须通过 `x-rosetta-upstream: <name>` header 显式指定 upstream。原设计里按 `model_glob` 自动匹配 upstream 的 `routes` 表已经移除(2026-04 简化),单个 http 请求的选 upstream 流程只剩一步:

```
1. header 有 x-rosetta-upstream: <name>?
   · 有 → 按 name 精确匹配 upstream
      · 找到 enabled → 用它
      · 不存在 → 400 upstream_not_found
      · 被禁用 → 400 upstream_disabled
   · 没有 → 400 missing_rosetta_upstream
```

**关于选中的 upstream 与入口 format**:选中 upstream 的 `protocol` 与入口 format 不一致时,自动走 §8.3 翻译(对角线直通仅发生在两者一致的情况)。例如入口 `/v1/messages` + upstream `protocol=completions` → IR 翻译为 Chat Completions 请求。

**错误响应体**:

```json
{
  "error": {
    "type": "rosetta_error",
    "code": "upstream_not_found",   // 或 missing_rosetta_upstream / upstream_disabled
    "message": "x-rosetta-upstream 指定的 'ghost' 不存在"
  }
}
```

该结构**不伪装**上游格式(不套 Claude/OpenAI 的错误壳),由 CLI / GUI 识别 `error.type == "rosetta_error"` 后格式化展示。

**客户端配合**:
- `rosetta chat --upstream <name>` 自动注入 header
- GUI Chat 页 "Upstream 下拉" 必选,每次发送都带 header
- 外部 SDK 调用:应用层在 HTTP client 里统一加 header(upstream 是"环境配置")

### 8.5 端到端请求链路（以 CLI chat 为例）

把前面几节串起来，跟一遍 `rosetta chat --protocol messages "hi" --model claude-haiku-4-5` 从敲下命令到拿到第一个 token 的完整路径。（演示的是**正常模式**，客户端**不传** `--api-key`，靠 server 里存的 `upstreams.api_key` 兜底。）

```
┌─────────────┐                 ┌───────────────────────┐                ┌──────────────────┐
│ rosetta CLI │                 │ rosetta-server        │                │ 真实 LLM 服务    │
│ (本机)      │                 │ (本机 127.0.0.1:PORT) │                │ (api.anthropic…) │
└──────┬──────┘                 └──────────┬────────────┘                └────────┬─────────┘
       │                                    │                                     │
       │ 1. 读 ~/.rosetta/endpoint.json     │                                     │
       │    → url + port                    │                                     │
       │                                    │                                     │
       │ 2. POST /v1/messages               │                                     │
       │    （无 x-api-key，靠 server 兜底）│                                     │
       │    body.model: claude-haiku-4-5    │                                     │
       │    body.messages: [...]            │                                     │
       │ ─────────────────────────────────► │                                     │
       │                                    │ 3. loopback 校验通过（只接 127.*）  │
       │                                    │ 4. 按 x-rosetta-upstream header     │
       │                                    │    选 upstream "anthropic-main"     │
       │                                    │ 5. 读 upstreams 行:                 │
       │                                    │    base_url → https://api.anth…     │
       │                                    │    api_key  → sk-ant-XXXX           │
       │                                    │ 6. 解析上游 api-key:                │
       │                                    │    请求头有 x-api-key? 用它         │
       │                                    │    没有 → 用 upstreams.api_key      │
       │                                    │    （这里走"没有"分支）              │
       │                                    │ 7. format=messages + type=anthropic │
       │                                    │    → 3×3 对角线直通，零翻译         │
       │                                    │                                     │
       │                                    │ 8. httpx.post(                      │
       │                                    │     url:     {base_url}/v1/messages │
       │                                    │     headers: x-api-key=sk-ant-XXXX  │
       │                                    │                 （按上游 type 选对  │
       │                                    │                  应的鉴权头写法）   │
       │                                    │     json:    原样 body              │
       │                                    │   )                                 │
       │                                    │ ──────────────────────────────────► │
       │                                    │                                     │
       │ 9. SSE 事件流（原样转发）          │ ◄────────────────────────────────── │
       │ ◄───────────────────────────────── │                                     │
       │                                    │ 10. 异步写 logs                     │
       │ 11. 按 format 解码，逐 token 打印  │     (upstream_id, tokens, latency)  │
```

#### 关键字段的来源与去向

| 字段 | 链路步骤 | 来源 | 去向 | 备注 |
|---|---|---|---|---|
| 上游 URL | 8 | `upstreams.base_url`（空则按 type 默认，见 §8.2） | httpx 请求行 | 用户在 GUI / `upstream add` 填一次 |
| 上游 api-key | 8 | **客户端 `x-api-key` 头**（若带）→ **否则 `upstreams.api_key`** | httpx 请求头（按上游 type 选具体写法） | v0 无"rosetta 本地 key"概念 |
| `model` | 2 → 8 | CLI `--model` 参数 | 上游 `body.model` 原样 | v0 不做别名翻译 |
| `messages[]` | 2 → 8 | CLI 内存数组（多轮历史） | 上游 body（直通）或 adapter 翻译后（跨格式） | |
| `x-rosetta-upstream: foo`（**必须**） | 2 | CLI `--upstream foo` | server 按 name 查 upstream | **不转发上游**;缺失直接 400 |

#### 客户端显式传 `--api-key` 的分支

`rosetta chat --api-key sk-XYZ --model claude-haiku-4-5 "hi"`：在步骤 2 的请求里带上 `x-api-key: sk-XYZ`，步骤 6 检测到就用这把，**不**读 `upstreams.api_key`。其他步骤完全不变。这条分支让你"临时用一把不一样的 key 试试"不需要改任何 DB 配置。

#### direct 模式的旁路（见 §8.7）

`rosetta chat --base-url ... --api-key ... "hi"`：步骤 2 打的不是 127.0.0.1 而是上游 URL，压根不经 server，后面的 3~10 都不发生。server 连被调用都感知不到。同一个 `--api-key` flag、同一个 HTTP 鉴权头机制，在两种模式里意思完全一致。

### 8.6 直连（BYOK）模式

客户端绕开本地 server 直接打上游，用于"试 key / CI 脚本 / server 挂了应急"。

**触发规则**：CLI / GUI 请求时**解析到非空 `--base-url`**（来自 flag 或 `ROSETTA_DIRECT_BASE_URL` env）→ 走 direct。否则走正常模式。**不需要单独的 `--direct` 开关**。

**必填四件套**（任一缺失就 exit 2 / 前端报错）：

| 参数 | CLI flag | env | 含义 |
|---|---|---|---|
| 上游 URL | `--base-url` | `ROSETTA_DIRECT_BASE_URL` | 上游根地址，不带 `/v1` 不带尾斜杠 |
| 上游 api-key | `--api-key` | `ROSETTA_DIRECT_API_KEY` | 直接写到 `x-api-key` 或 `Authorization: Bearer`（按 `--format` 的约定） |
| 方言 | `--format` | `ROSETTA_DIRECT_FORMAT` | `messages\|completions\|responses`，**必须 = 上游原生格式**（v0 不翻译） |
| 模型 | `--model` | `ROSETTA_DIRECT_MODEL` | 上游能识别的模型名 |

**direct 模式不支持的事**：

- **不翻译**：`--format` 和上游方言不一致 → exit 2 提示"去掉 --base-url 或改 format"。要跨格式请走正常模式。
- **不路由**:没有 `upstreams` / `x-rosetta-upstream` 概念介入。
- **不记日志 / 不计 stats**：不经过 server，`logs` 表里就没这条记录。
- **GUI 浏览器环境用不了**：CORS 会阻止浏览器直打 `api.anthropic.com`。Tauri 桌面端可以通过 `tauri.conf.json` 的 `http.scope` allowlist 绕过；纯浏览器开发环境下 GUI 的 direct 开关直接禁用。

**与服务端语义的互斥参数**：direct 模式压根不经 server，任何"让 server 做事"的参数都无意义，传了就 exit 2:

| 与 `--base-url` 互斥 | 原因 |
|---|---|
| `--upstream <name>` / `x-rosetta-upstream` 头 | direct 模式没有 upstream 概念 |
| 让翻译器介入的 format 切换 | direct 模式不翻译，`--format` 必须 = 上游原生格式 |

CLI 在 argparse 阶段校验；SDK 的 `ProxyClient.direct(...)` 构造函数不暴露这些参数。

**meta 行显示**（CLI 和 GUI 一致）：

```
[direct · api.anthropic.com · claude-haiku-4-5 · 8→18 tokens · 412ms]
 ↑ direct 模式用 hostname 作为"upstream"位，因为没有 name 可取
```

**和正常模式的对照**：

| | 正常模式 | direct 模式 |
|---|---|---|
| 触发 | 不传 `--base-url` | 传 `--base-url`（flag 或 env） |
| 经 server | 是 | 否 |
| api-key 来源 | `x-api-key` 头若有则 override，否则 `upstreams.api_key` fallback | 必填，直接走 `x-api-key` / `Authorization` |
| URL 来源 | `upstreams.base_url`（按 `x-rosetta-upstream` header 查 name） | `--base-url` 直填 |
| 可跨格式翻译 | 可以（走 IR） | 不可以（必须原生） |
| 日志 / stats | 写 | 不写 |

---

## 9. SDK 设计（`rosetta.sdk` 子包）

CLI 不直接调 HTTP，而是通过 SDK 子包：

```python
# rosetta/sdk/client.py
from rosetta.sdk import ProxyClient

async with ProxyClient.discover() as client:
    # .discover() 内部：
    # 1. 读 endpoint.json
    # 2. 不存在/死了 → spawn server
    # 3. 等 ready（轮询 /admin/ping）
    # 4. 拿 url + token 建 httpx.AsyncClient
    status = await client.status()
    upstreams = await client.list_upstreams()
    await client.create_upstream(name="...", protocol="messages", api_key="...")
```

Pydantic 模型直接 `from rosetta.server.schemas.admin import Upstream` 复用，**不手写第二份**——单包结构下子包互相 import 无需包依赖声明。

---

## 10. CLI 设计（`rosetta.cli` 子包）

```bash
# server 管理
rosetta start              # 后台启动 server（守护模式，立即返回）
rosetta stop               # 优雅关停
rosetta status             # 状态概览
rosetta serve              # 前台启动（开发调试用，同 rosetta-server serve）

# upstream 管理
rosetta upstream list
rosetta upstream add --name foo --protocol messages --api-key sk-ant-...
rosetta upstream remove <id>
rosetta upstream test foo

# 观测
rosetta logs -n 50
rosetta stats today

# 对话（多轮 REPL + 一次性）
rosetta chat                             # 进入 REPL，多轮对话（历史保存在进程内存中）
                                         #   /exit 退出、/reset 清空会话、/model X 切模型
rosetta chat "hello"                     # 一次性：单轮，打印完退出
echo "hello" | rosetta chat              # stdin 作为 prompt：一次性
rosetta chat --model claude-haiku-4-5 "hi"
rosetta chat --protocol completions        # 入口格式，默认 messages（messages | completions | responses）
                                         #   分别对应 /v1/messages、/v1/chat/completions、/v1/responses
rosetta chat --upstream foo "hi"         # 必填:指定 upstream(带 x-rosetta-upstream header)
rosetta chat --api-key sk-ant-XXX "hi"   # 可选:覆盖 upstreams.api_key，临时用另一把上游 key
rosetta chat --no-stream                 # 关流式（默认开，SSE 边出边打）
rosetta chat --json                      # 一次性：打印完整响应 JSON，不做渲染（方便脚本）

# 直连（BYOK）模式：传 --base-url 即触发，绕过 server，详见 §8.6
rosetta chat \
    --format messages \
    --base-url https://api.anthropic.com \
    --api-key sk-ant-XXX \
    --model claude-haiku-4-5 "hi"
```

### `rosetta chat` 设计要点

- **REPL 多轮**：客户端在内存里维护 messages 数组，每次把**完整历史**作为请求体发给 `/v1/*`——API 本身无状态，会话是客户端侧的事。`/reset` 清空数组，`Ctrl+D` / `/exit` 退出。
- **一次性模式**（带 `"text"` 参数或 stdin 管道）：发完即退，不保留历史，也不写任何本地文件——这是"启动后测一下链路通不通"的最小形态。
- **鉴权**：CLI **不持有任何 rosetta 自有的本地 key**——server 不做 API-level auth（loopback-only）。`--api-key` 是**可选的上游 key override**：传了就附加 `x-api-key: <你的值>` 让 server 透传；不传就让 server 用 `upstreams.api_key`。direct 模式下 `--api-key` 是必填。
- **direct 模式触发**：命令里（或 env）出现 `--base-url` → 直接打上游，不经 server。详见 §8.6。
- **已知局限**（v0 故意不处理）：REPL 中切换 `/model` 或 `--format` 时，前文只保留 text block（role=user/assistant）；工具调用 / thinking / 图片等块在 format 切换后丢弃并打印 warning——"切格式 = 新对话的开始"比"翻译前文"简单太多。

### CLI 完整使用 demo（从零到多轮对话）

假设全新机器，刚装完 `rosetta.exe`。下面每一步的注释标出是本机第几次访问什么资源。

```bash
# ─── step 1：启动 server ─────────────────────────────────────────
$ rosetta start
→ spawn rosetta-server.exe，写 ~/.rosetta/endpoint.json（url+admin token+pid）
→ server 只绑 127.0.0.1，不做 API-level auth
server started on http://127.0.0.1:62538 (pid 12345)

# ─── step 2：加一个真实上游 upstream ─────────────────────────────
$ rosetta upstream add \
    --name anthropic-main \
    --type anthropic \
    --api-key sk-ant-api03-XXXXXXXXXXXXXXXX
→ POST /admin/upstreams，server 写 SQLite（base_url 留空→默认 https://api.anthropic.com）
upstream "anthropic-main" created (id=1, base_url=https://api.anthropic.com)

# ─── step 3：确认状态 ──────────────────────────────────────────
$ rosetta status
server:    http://127.0.0.1:62538  (uptime 12s)
upstreams: 1 enabled (anthropic-main)

# ─── step 4：一次性对话（最小链路自检）──────────────────────────
$ rosetta chat --upstream anthropic-main "用一句话介绍你自己"
→ POST /v1/messages to 127.0.0.1:62538
   header: x-rosetta-upstream: anthropic-main
   （无 x-api-key，让 server 用 upstreams.api_key 兜底）
   body.model: claude-haiku-4-5          ← 内置默认模型（type=anthropic→haiku）
→ server: 按 header 选中 anthropic-main → 用 upstreams.api_key sk-ant-XXX
→ httpx.post https://api.anthropic.com/v1/messages with sk-ant-XXX
← SSE 流回来

我是 Claude，一个由 Anthropic 训练的 AI 助手。
[anthropic-main · claude-haiku-4-5 · 12→18 tokens · 812ms · messages↔messages 直通]

# ─── step 5：进入 REPL 玩多轮 ──────────────────────────────────
$ rosetta chat
rosetta chat · format=messages · model=claude-haiku-4-5
commands: /exit  /reset  /model <name>  /format <name>
> 1 + 1 等于几？
2。
> 再乘以 5 呢？
10。
  ↑ 这里发的请求 body.messages 里带了前两轮（4 条消息）；历史由 CLI 在内存里拼
> /model claude-sonnet-4-5
model switched to claude-sonnet-4-5 (next turn)
> 刚才那个结果是多少？
你上一轮得到的是 10。
> /exit

# ─── step 6：加第二个 upstream + 跨格式翻译验证 ──────────────────
$ rosetta upstream add --name openai-main --protocol completions --api-key sk-XXX

# CLI 用 messages 格式打 OpenAI → server 走翻译 messages→IR→completions
$ rosetta chat --upstream openai-main --model gpt-4o-mini "hi"
Hello! How can I help you today?
[openai-main · gpt-4o-mini · 8→9 tokens · 402ms · messages→IR→completions]

# CLI 用 completions 格式打 OpenAI → 对角线直通
$ rosetta chat --upstream openai-main --format completions --model gpt-4o-mini "hi"
Hello! How can I help you today?
[openai-main · gpt-4o-mini · 8→9 tokens · 398ms · completions↔completions 直通]

# 切回 Anthropic upstream
$ rosetta chat --upstream anthropic-main --format messages --model claude-haiku-4-5 "ping"
pong
[anthropic-main · claude-haiku-4-5 · 4→2 tokens · 312ms · messages↔messages 直通]

# ─── step 7：临时换一把 api-key 测试（不修改 upstream）──────────────
$ rosetta chat --upstream anthropic-main --api-key sk-ant-OTHER --model claude-haiku-4-5 "hi"
  ↑ server 收到请求头带 x-api-key，就拿这把去打上游，不读 upstreams.api_key

# ─── step 8：direct 模式（完全绕过 server）───────────────────────
$ rosetta chat \
    --format messages \
    --base-url https://api.anthropic.com \
    --api-key sk-ant-XXX \
    --model claude-haiku-4-5 "hi"
  ↑ 传了 --base-url → 触发 direct，httpx 直打上游
我是 Claude，...
[direct · api.anthropic.com · claude-haiku-4-5 · 12→18 tokens · 412ms]
```

**观察点**：

1. **server 没有自己的 key 概念**——step 4 里 CLI 没传 `x-api-key`，server 用 upstreams 里存的；step 7 里 CLI 传了,server 就透传。概念统一。
2. **meta 行的翻译路径**（`直通` / `→IR→`）是活体自检的核心信号——启动后打一条 `rosetta chat "ping"` 看 meta 就知道链路是否贯通。
3. **多轮靠客户端**：step 5 第二轮的"再乘以 5"能被理解，是因为 CLI 把前两轮一起塞进了 `body.messages`；server 无状态，纯转发。
4. **upstream 必须显式指定**:rosetta 不做 model-based 自动路由,客户端每次都带 `x-rosetta-upstream` header(`--upstream <name>`);没带直接 400。
5. **direct 模式**（step 8）是个旁路：`--base-url` 触发,不经 server,不记日志,也不翻译——要跨格式就去掉 `--base-url` 走 server。

---

## 11. GUI 设计（`packages/app` + `packages/desktop`）

### 页面清单（v0 功能）

1. **Dashboard** — 状态、今日请求数、错误率、在跑的 upstream 列表
2. **Upstreams** — 表格 + 新增/编辑 Modal（shadcn/ui 的 Dialog + Form）
3. **Logs** — 请求列表 + 按 upstream / 时间筛选
4. **Chat** — 多轮对话测试页，upstream / format / model 可选，流式渲染；消息保存在**当前页面的 React state**，切页或刷新即清（v0 不做持久化，见下节）

（v0 **没有 Keys 页**——rosetta 不再有自有的"本地 key"概念，上游 api-key 在 Upstreams 页编辑 upstream 时填入。见 §8 鉴权说明。）

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

### Chat 页详细设计

```
┌─ Chat ────────────────────────────────────────────┐
│ Upstream: [anthropic-main ▾]  Format: [messages ▾] │
│ Model:    [claude-haiku-4-5 ▾]    [New chat]     │
├───────────────────────────────────────────────────┤
│  🧑 hello                                         │
│  🤖 hi! how can i help? …（流式增量）              │
│  🧑 ...                                           │
├───────────────────────────────────────────────────┤
│ [ 输入框                       ] [Send] [⏸ Stop]   │
│ meta: 8→21 tokens · 823ms · messages↔messages 直通 │
└───────────────────────────────────────────────────┘
```

- **状态**：当前会话的 `messages[]` 用 `useState` 存在 Chat 页组件里，**不入 DB、不入全局 store**、切页或刷新即清。想要多会话 / 历史翻阅请用外部 chat 客户端连 rosetta（见 §1 定位）。
- **Upstream 下拉**:必填,挂载时拉 `GET /admin/upstreams` 填充选项;每次发送都带 `x-rosetta-upstream: <name>` header。没选 upstream 不能点发送。
- **Format 下拉**:三选一 `messages | completions | responses`(对应 `/v1/messages` / `/v1/chat/completions` / `/v1/responses`),默认 `messages`。切换后下次发送用新格式的请求体构造;已渲染的历史消息不回放。已知局限和 CLI 相同——切 format 后前文的 tool_use / thinking / image 块丢弃并给 toast 提示。
- **Model 下拉**:来源 `GET /v1/models?format=<当前>&upstream=<Upstream 下拉值>`,随 format / upstream 联动。
- **流式**：浏览器 `fetch` + `ReadableStream` 读 SSE，按当前 format 解码后逐 token 追加到 assistant 气泡；`Stop` 按钮 `AbortController.abort()`。
- **鉴权**：前端对本地 server **不带任何 rosetta 自有的 key**——server 只绑 loopback,不做 API-level auth。`/v1/*` 请求默认**不加 `x-api-key` 头**,让 server 用 `upstreams.api_key` 兜底。可选的"临时换 key 测试"场景在页面右上角提供一个小入口("Override api-key"),存会话内存、不落盘、切页即清。
- **New chat**：清空 messages 数组 = 清历史（本就只在内存里）。
- **错误态**：上游 4xx/5xx 渲染成红色系统气泡，保留原始 JSON 可一键复制，方便排障。

**v1+ 可选扩展**：多会话侧栏 + 持久化（新增 `conversations` / `messages` 表 + `/admin/conversations/*`）、会话导出、原始请求/响应 JSON 预览面板。这些是 scope 外的东西，v0 刻意不做。

### GUI 完整使用 demo（从零到多轮对话）

双击 `Rosetta.exe`，第一次打开：

**① 首次启动（零配置）**

```
┌─ Rosetta ──────────────────────────────────┐
│ ⚙ 正在启动本地 server …                     │
│   → spawn rosetta-server.exe (sidecar)      │
│   → 前端收到 url + admin token              │
│   → server 只绑 127.0.0.1，无 API-level auth │
│ ✓ 就绪                                      │
└────────────────────────────────────────────┘
```

**② Dashboard 空态引导**

```
┌─ Dashboard ────────────────────────────────┐
│ ⚠ 当前没有启用的 upstream，无法发起对话     │
│                                            │
│      [ + 添加 Upstream ]                   │
└────────────────────────────────────────────┘
```

**③ 点按钮跳 Upstreams → 弹 Modal 填第一个 upstream**

```
┌─ New Upstream ──────────────────────────────┐
│ Name     [ anthropic-main              ]    │
│ Type     [ anthropic             ▾ ]        │
│ Base URL [                             ]    │
│          （留空使用 https://api.anthropic.com）│
│ API Key  [ sk-ant-api03-XXXXXXXXXXXX   ]    │
│ [x] Enabled                                 │
│                         [ Cancel ] [ Save ] │
└────────────────────────────────────────────┘
```

Save 后 `POST /admin/upstreams` → 写 SQLite。Dashboard 顶部警告消失。

**④ 切到 Chat 页 → 自动就绪**

```
┌─ Chat ────────────────────────────────────────────┐
│ Upstream: [anthropic-main ▾]  Format: [messages ▾] │
│ Model:    [claude-haiku-4-5 ▾]    [New chat]     │
│   ↑ 挂载时调 GET /v1/models?format=messages 填充   │
├───────────────────────────────────────────────────┤
│  🧑 hello                                         │
│  🤖 hi! how can i help? ⎯ (流式增量)              │
├───────────────────────────────────────────────────┤
│ [ ...                          ] [Send] [⏸ Stop]  │
│ meta: 12→18 tokens · 812ms · messages↔messages 直通│
└───────────────────────────────────────────────────┘
```

每次 Send：

```
fetch(`${url}/v1/messages`, {
  method: 'POST',
  headers: {
    // 默认不带任何鉴权头，server 会用 upstreams.api_key 兜底。
    // 用户在右上角 "Override api-key" 输入了临时 key 时才加这一行：
    //   'x-api-key':        <override key>,
    'x-rosetta-upstream': <Upstream 下拉选中的 name>,   // 必填
    'content-type':       'application/json',
  },
  body: JSON.stringify({
    model:    <Model 下拉>,
    messages: [...state.messages, { role: 'user', content: inputText }],
    stream:   true,
  }),
  signal: abortController.signal,
})
```

**⑤ 格式切换活体验收**

Format 下拉从 `messages` 切到 `completions`：

- Model 下拉重新拉 `GET /v1/models?format=completions`（选到 `responses` 时同样传 `format=completions`——Responses API 的 models 列表是 OpenAI shape，复用这一路）
- 下一条发送走对应的端点 `/v1/chat/completions` 或 `/v1/responses`
- meta 行变成 `messages→IR→completions` 或 `completions↔completions`，取决于被路由到哪个 upstream 类型
- **以前发过的消息气泡不动**（§11 已知局限：前文的 tool_use / thinking / image 块在新 format 下会丢，UI 以 toast 提示）

这就是文档开头讲的"翻译矩阵 9 条路径"的手动回归测试——页面上切两个下拉 + 发一条消息，一次验证一格。

**⑥ 错误路径的呈现**

假如 `api_key` 填错了：

```
🤖 ✗ 401 authentication_error                          [复制原始 JSON]
   invalid x-api-key

   upstream:  anthropic-main
   upstream:  https://api.anthropic.com/v1/messages
```

直接定位"上游鉴权失败" → 用户回 Upstreams 页改 key → 重试。无需 tail 日志。

**⑦ New chat / 关窗**

- `New chat` 按钮清空 React state 的 `messages[]`。历史本就只在内存，等于清空。
- 关窗 → Tauri `on_close` → 调 `POST /admin/shutdown` → server 优雅退出。下次开窗从 endpoint.json 重建。

**整个流程里用户只在 step ③ 填过一次 api-key**——之后 UI 里再也不出现,上游 key 始终存在 SQLite 里由 server 代为注入。不需要任何 rosetta 自有的本地 key、不需要手工复制粘贴任何鉴权串。

---

## 12. 部署与打包

### 开发

```bash
# 装依赖（Python 侧一条 uv sync 搞定整个 rosetta 包）
uv sync

# 启 server（dev 模式，reload）—— 在 repo 根执行
uv run uvicorn rosetta.server.main:app_factory --factory --reload

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
# 1. 打包 server 成单 exe —— 在 repo 根执行
uv run pyinstaller --onefile --name rosetta-server \
  --hidden-import aiosqlite \
  rosetta/server/__main__.py
#   产物：dist/rosetta-server.exe

# 2. 打包 CLI
uv run pyinstaller --onefile --name rosetta \
  rosetta/cli/__main__.py
#   产物：dist/rosetta.exe

# 3. 桌面打包（自动把 server exe 打进安装包）
cd packages/desktop
# tauri.conf.json 里声明：
#   "bundle": {
#     "externalBin": ["binaries/rosetta-server"]
#   }
# 产物：Rosetta-setup.exe
pnpm tauri build
```

**关于 exe 大小**：两个 exe 都会把整个 `rosetta` 包打进去（包含 server/sdk/cli 三个子包），但 PyInstaller 按实际 import 关系裁剪——CLI 通过 HTTP 调 server，并不真的 import `rosetta.server.*`，实际产物大小和旧三包方案接近。

---

## 13. 风险与待决议项

### 已识别的风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **自研翻译层边缘 case** | 多模态 / 罕见 tool_choice 组合 / 特殊 stop_reason 翻译不准 | 金标样本集 + 每条路径 E2E 测试；无法翻译的字段落入 `_extras` 保留；非关键字段丢失返回 warning 头 |
| **流式状态机 bug** | SSE 翻译错位导致客户端 SDK 解析失败 | 翻译器用状态机明确转移图；对每个 adapter 写 fixture-based 流式回归测试 |
| **Responses API 有状态特性** | 翻译到 Completions/Messages 时丢失会话上下文 | 明确降级策略（§8.3），客户端发 `previous_response_id` 且上游非 Responses 时直接 400 |
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

## 14. 参考资料

- [opencode 架构分析](../../claude_test/opencode.md) — 同款 sidecar + Tauri 模式，可参考其 Platform 抽象和三层分包
- cc-switch（https://github.com/farion1231/cc-switch）— 同类产品，UI/交互可参考
- [Tauri 2.x externalBin/sidecar](https://v2.tauri.app/develop/sidecar/)
- [Anthropic Messages API](https://docs.anthropic.com/en/api/messages) — Claude Messages 官方文档
- [OpenAI Chat Completions](https://platform.openai.com/docs/api-reference/chat) — OpenAI Chat 官方文档
- [OpenAI Responses](https://platform.openai.com/docs/api-reference/responses) — OpenAI Responses 官方文档
- [LiteLLM 文档](https://docs.litellm.ai/) — 可选参考；Chat Completions ↔ Claude 的字段映射逻辑可对照它的实现，但本项目不依赖此库

---

_本文档是实施前的唯一信息源。有改动请在此文档更新后再动代码。_
