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
├── README.md                    # 项目简介(留根,GitHub 默认渲染)
├── docs/
│   ├── DESIGN.md                # 本文档(架构真源)
│   ├── FEATURE.md               # v0 分步任务清单(heading emoji 标进度)
│   ├── ROADMAP.md               # v1+ 后续方向
│   ├── archive/                 # 已归档备选方案
│   └── guides/                  # 教学型指南(cli-typer / database / uv-toolchain ...)
├── CLAUDE.md                    # Claude 会话协作约定(项目级)
├── pyproject.toml               # Python 包 rosetta 定义(依赖 / entry points / 工具配置)
├── uv.lock
├── package.json / bun.lock      # bun workspace 根(声明 packages/app、packages/desktop)
├── scripts/build.py             # PyInstaller 打包驱动(CLI + server + sidecar 同步)
├── build/                       # PyInstaller spec
│   ├── rosetta.spec             # CLI 打包规格
│   └── rosetta-server.spec      # server 打包(windowless,console=False)
├── .github/workflows/
│   ├── ci.yml                   # push/PR: ruff + pyright + pytest(matrix windows/ubuntu)
│   └── release.yml              # push tag v*: 两段式 PyInstaller exe → Tauri installer
│
├── rosetta/                     # Python 源码
│   ├── __init__.py
│   ├── shared/
│   │   ├── __init__.py
│   │   └── protocols.py         # Protocol 枚举(messages/completions/responses) + UPSTREAM_PATH
│   │
│   ├── server/
│   │   ├── __init__.py
│   │   ├── __main__.py          # python -m rosetta.server -> uvicorn + endpoint.json + parent-watch
│   │   ├── app.py               # FastAPI app factory + lifespan(init_db / forwarder.open)
│   │   │
│   │   ├── controller/          # HTTP 层:endpoint + exception handler
│   │   │   ├── __init__.py      # admin_router + dataplane_router + register_exception_handlers
│   │   │   ├── runtime.py       # /admin/ping · /admin/status · /admin/shutdown
│   │   │   ├── upstreams.py     # /admin/upstreams CRUD + /admin/upstreams/restore-mock
│   │   │   ├── logs.py          # GET /admin/logs(limit/offset/upstream/since/until)
│   │   │   ├── stats.py         # GET /admin/stats?period=today|week|month
│   │   │   ├── dataplane.py     # POST /v1/messages · /v1/chat/completions · /v1/responses
│   │   │   └── errors.py        # rosetta_error(code, message, **extra) 错误响应体工厂
│   │   │
│   │   ├── service/             # 业务层:不依赖 HTTP / FastAPI
│   │   │   ├── __init__.py
│   │   │   ├── forwarder.py     # Forwarder + 单例:httpx 转发 + 翻译编排 + SSE 透传 + logs 埋点
│   │   │   ├── mock.py          # MockResponder + 单例:provider=mock 本地 echo(IR 全链路)
│   │   │   ├── selector.py      # pick_upstream:按 x-rosetta-upstream header 选 upstream
│   │   │   ├── log_writer.py    # LogWriter + 单例:请求流水后台写库,失败只 warn 不冒泡
│   │   │   └── exceptions.py    # ServiceError(status, code, message, **extra) domain exception
│   │   │
│   │   ├── repository/          # 数据访问层:ORM 查询封装
│   │   │   ├── __init__.py      # re-export + UpstreamRepoDep / LogRepoDep FastAPI 依赖别名
│   │   │   ├── upstream.py      # UpstreamRepo + MOCK_UPSTREAM_FIELDS(mock seed 身份)
│   │   │   └── log.py           # LogRepo(create / list_with_upstream / aggregate_stats)
│   │   │
│   │   ├── database/            # infra:engine / session / ORM / migrations
│   │   │   ├── __init__.py
│   │   │   ├── models.py        # Base + Upstream(provider + protocol 含 any)+ LogEntry
│   │   │   ├── session.py       # async engine + session_maker + init_db/dispose_db
│   │   │   └── migrations/
│   │   │       ├── __init__.py
│   │   │       └── 001_init.sql # upstreams + logs DDL + mock seed + user_version=1
│   │   │
│   │   ├── translation/         # 纯工具:跨格式翻译(无状态)
│   │   │   ├── __init__.py
│   │   │   ├── ir.py            # RequestIR / ResponseIR / StreamEvent(Anthropic 风格镜像)
│   │   │   ├── dispatcher.py    # translate_request / translate_response / translate_stream_*
│   │   │   ├── sse.py           # parse_sse_stream / encode_sse_stream
│   │   │   ├── degradation.py   # Responses -> 非 Responses 的降级预处理
│   │   │   ├── messages/        # Protocol.MESSAGES(Anthropic)
│   │   │   ├── completions/     # Protocol.CHAT_COMPLETIONS(OpenAI Chat)
│   │   │   └── responses/       # Protocol.RESPONSES(OpenAI Responses)
│   │   │
│   │   └── runtime/             # 进程生命周期 + 日志配置
│   │       ├── endpoint.py      # 读/写 ~/.rosetta/endpoint.json(.tmp -> rename 原子)
│   │       ├── lockfile.py      # spawn.lock 独占创建 + PID 陈旧检测
│   │       ├── watcher.py       # parent PID 监控 + 5 步优雅关闭
│   │       └── logger.py        # configure_logging():stdout handler + utf-8 重配 + uvicorn logger 接管
│   │
│   ├── sdk/                     # HTTP 客户端:CLI 用 + 外部脚本复用
│   │   ├── __init__.py
│   │   ├── client.py            # ProxyClient:discover_session / direct_session · admin + dataplane 合一
│   │   ├── discover.py          # 读 endpoint.json;不存在就 spawn server(detach)
│   │   └── streams.py           # iter_text_deltas / ChatStream:三协议 SSE -> 文本 + usage 抽取
│   │
│   └── cli/                     # 终端命令行(typer)
│       ├── __init__.py
│       ├── __main__.py          # python -m rosetta.cli -> typer 根命令 + --quiet / -q
│       ├── core/                # 共用工具:render / context / 执行模式
│       │   ├── render.py        # Renderer 名空间类:流式 token / meta 行 / 错误气泡 / 表格
│       │   ├── context.py       # ChatContext:会话配置 + 多轮历史 + run_turn 编排
│       │   ├── repl.py          # ChatRepl:REPL 循环 + slash 命令分派
│       │   ├── once.py          # ChatOnce:一次性模式执行器
│       │   └── batch.py         # 批量模式占位(预留)
│       └── commands/
│           ├── status.py        # rosetta status
│           ├── start.py         # rosetta start(detach 拉起 server)
│           ├── stop.py          # rosetta stop
│           ├── upstream.py      # rosetta upstream add/list/remove/mock(mock 恢复)
│           ├── logs.py          # rosetta logs [-f] [--upstream] [--limit]
│           ├── stats.py         # rosetta stats
│           └── chat.py          # rosetta chat:server 模式 + direct 模式二合一
│
├── tests/
│   ├── server/                  # controller + service + repository 单测 + 集成
│   ├── sdk/                     # ProxyClient + discover
│   ├── cli/                     # typer 子命令接线(不调 server)
│   └── translation/             # IR / adapter / 流式状态机金标
│
└── packages/                    # 非 Python 工作区成员
    ├── app/                     # 前端:React + Vite + Tailwind + shadcn
    │   ├── package.json
    │   ├── vite.config.ts
    │   ├── vite-plugin-rosetta-proxy.ts  # per-request 动态代理 /admin /v1 到 endpoint.json
    │   └── src/
    │       ├── main.tsx
    │       ├── App.tsx          # 根布局 + ServerStatusBanner
    │       ├── routes.tsx
    │       ├── lib/
    │       │   ├── api.ts       # /admin/* 薄封装 + UpstreamOut / LogOut 类型
    │       │   ├── chat.ts      # 数据面 /v1/* fetch + AbortController + override api-key
    │       │   ├── streams.ts   # 三协议 SSE 解码(TS 版对照 Python sdk/streams.py)
    │       │   └── updater.ts   # Tauri plugin-updater invoke 封装 + isTauri() 检测
    │       ├── pages/           # Dashboard / Upstreams / Logs / Chat
    │       └── components/
    │           ├── Nav.tsx
    │           ├── ServerStatusBanner.tsx  # 10s 轮询 /admin/ping + 红条 + Retry
    │           └── ui/          # shadcn 组件
    │
    └── desktop/tauri/           # Tauri 2.x 外壳(直接叫 tauri/,不用 src-tauri)
        ├── Cargo.toml
        ├── tauri.conf.json      # externalBin / NSIS bundle / plugins.updater
        ├── capabilities/default.json  # core + shell:allow-execute(sidecar) + updater:default
        ├── binaries/            # rosetta-server-<triple>.exe sidecar(build.py --sync-sidecar 就位)
        ├── icons/
        └── src/
            ├── main.rs          # 入口
            └── lib.rs           # sidecar spawn + tray + window-state + updater commands
```

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

**provider=mock 短路**:`forwarder.forward` 入口判 `upstream.provider == "mock"`,命中就**不发 HTTP**,直接调 `MockResponder.respond(fmt, body, stream=...)` 本地合成 echo 响应。mock 的请求侧仍走 `_REQ_TO_IR[fmt]` 严格 Pydantic 校验(schema 不合规返 400 `mock_invalid_request`);响应侧按客户端入口 fmt 走对应的 `_IR_TO_RESP` / `_IR_TO_STREAM` 出口 + `encode_sse_stream`,三协议共用一条 IR 流水(见 `rosetta/server/service/mock.py`)。`upstream.protocol=any` 只是占位,mock 不读它。

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
| 上游 api-key | `--api-key` | `ROSETTA_DIRECT_API_KEY` | 直接写到 `x-api-key` 或 `Authorization: Bearer`(按 `--protocol` 的约定) |
| 方言 | `--protocol` | `ROSETTA_DIRECT_PROTOCOL` | `messages\|completions\|responses`,**必须 = 上游原生协议**(direct 模式不翻译) |
| 模型 | `--model` | `ROSETTA_DIRECT_MODEL` | 上游能识别的模型名 |

**direct 模式不支持的事**:

- **不翻译**:`--protocol` 和上游方言不一致 → 上游自己会 4xx 回错;rosetta 不介入。要跨格式请走正常模式。
- **不路由**:没有 `upstreams` / `x-rosetta-upstream` 概念介入。
- **不记日志 / 不计 stats**:不经过 server,`logs` 表里就没这条记录。
- **GUI 浏览器环境用不了**:CORS 会阻止浏览器直打 `api.anthropic.com`。Tauri 桌面端可以通过 `tauri.conf.json` 的 `http.scope` allowlist 绕过;纯浏览器开发环境下 GUI 的 direct 开关直接禁用。

**与服务端语义的互斥参数**:direct 模式压根不经 server,让 server 做事的参数无意义:

| 与 `--base-url` 的互斥行为 | 说明 |
|---|---|
| `--upstream <name>` / `x-rosetta-upstream` 头 | direct 模式下 `--upstream` **自动失效**并 stderr 打 warn(软互斥,见 FEATURE §4.4) |

CLI 在参数解析阶段处理互斥;SDK 的 `ProxyClient.direct_session(...)` 构造函数不暴露 `upstream` 参数。

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
    --protocol messages \
    --base-url https://api.anthropic.com \
    --api-key sk-ant-XXX \
    --model claude-haiku-4-5 "hi"
```

### `rosetta chat` 设计要点

- **REPL 多轮**：客户端在内存里维护 messages 数组，每次把**完整历史**作为请求体发给 `/v1/*`——API 本身无状态，会话是客户端侧的事。`/reset` 清空数组，`Ctrl+D` / `/exit` 退出。
- **一次性模式**（带 `"text"` 参数或 stdin 管道）：发完即退，不保留历史，也不写任何本地文件——这是"启动后测一下链路通不通"的最小形态。
- **鉴权**：CLI **不持有任何 rosetta 自有的本地 key**——server 不做 API-level auth（loopback-only）。`--api-key` 是**可选的上游 key override**：传了就附加 `x-api-key: <你的值>` 让 server 透传；不传就让 server 用 `upstreams.api_key`。direct 模式下 `--api-key` 是必填。
- **direct 模式触发**：命令里（或 env）出现 `--base-url` → 直接打上游，不经 server。详见 §8.6。
- **已知局限**(v0 故意不处理):REPL 中切换 `/model` 或 `/protocol` 时,前文只保留 text block(role=user/assistant);工具调用 / thinking / 图片等块在 protocol 切换后丢弃并打印 warning——"切协议 = 新对话的开始"比"翻译前文"简单太多。

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
$ rosetta chat --upstream openai-main --protocol completions --model gpt-4o-mini "hi"
Hello! How can I help you today?
[openai-main · gpt-4o-mini · 8→9 tokens · 398ms · completions↔completions 直通]

# 切回 Anthropic upstream
$ rosetta chat --upstream anthropic-main --protocol messages --model claude-haiku-4-5 "ping"
pong
[anthropic-main · claude-haiku-4-5 · 4→2 tokens · 312ms · messages↔messages 直通]

# ─── step 7：临时换一把 api-key 测试（不修改 upstream）──────────────
$ rosetta chat --upstream anthropic-main --api-key sk-ant-OTHER --model claude-haiku-4-5 "hi"
  ↑ server 收到请求头带 x-api-key，就拿这把去打上游，不读 upstreams.api_key

# ─── step 8：direct 模式（完全绕过 server）───────────────────────
$ rosetta chat \
    --protocol messages \
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
- **Protocol 下拉**:三选一 `messages | completions | responses`(对应 `/v1/messages` / `/v1/chat/completions` / `/v1/responses`),默认 `messages`。切换后下次发送用新协议的请求体构造;已渲染的历史消息不回放。已知局限和 CLI 相同——切 protocol 后前文的 tool_use / thinking / image 块丢弃并给 toast 提示。
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

Protocol 下拉从 `messages` 切到 `completions`：

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
