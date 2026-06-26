# Rosetta

> 本地跑的 LLM API 格式转换中枢 · Claude Messages / OpenAI Chat Completions / OpenAI Responses **三格式任意互译**

用 Claude Code 调 OpenAI 模型、用 OpenAI SDK 调 Claude 模型、在 Anthropic / OpenAI / OpenRouter / 国内中转站之间切换上游。客户端通常只需要改 `base_url`，格式差异由 Rosetta 在本机代理层处理。

---

## 1. 项目概览

### 1.1 能做什么

- **跨生态调用**: 客户端用任一主流 API 格式写，上游可以是任一主流 LLM 服务，中间格式差异由代理透明翻译。
- **多 upstream 集中管理**: 一个地方管所有 key / 用量统计；客户端通过 `r-upstream` header 显式选，或按入口 `server_api` 走 default upstream。
- **开箱即用**: CLI 一次性对话、REPL 多轮、Web 管理台、Tauri 桌面壳。
- **Raw 调试视图**: GUI Chat 和 CLI 都能查看实际发送的 request 与返回的 SSE frame；GUI 支持逐步展开和 JSON 解析，CLI 支持前/后 frame 裁剪与完整输出。

类比: cc-switch 的“AI 配置管家”概念 + 自研格式翻译引擎。cc-switch 切的是配置文件，本项目切的是运行时流量并做格式转换。

### 1.2 当前状态

**v0.3.2 · 核心链路已实现，持续打磨中**。

已落地:

- FastAPI 数据面 / 管理面
- 三 API 类型 IR 翻译
- CLI / SDK
- React 管理台
- Tauri 桌面壳
- PyInstaller 打包脚本

架构真源见 [docs/DESIGN.md](./docs/DESIGN.md)，分阶段实施清单见 [docs/FEATURE.md](./docs/FEATURE.md)。

---

## 2. 架构和技术栈

### 2.1 架构速览

```text
┌─────────────┐        ┌─────────────────────┐        ┌──────────────────┐
│  客户端      │ ─────► │  rosetta (本机代理)  │ ─────► │  真实 LLM 服务    │
│  任一格式    │        │  三格式路由 + IR 翻译 │        │  任一 upstream    │
└─────────────┘        └─────────────────────┘        └──────────────────┘
     Claude SDK              127.0.0.1:<port>              api.anthropic.com
     OpenAI SDK              /v1/messages                  api.openai.com
     curl / fetch            /v1/chat/completions          openrouter.ai
                             /v1/responses                 自建中转站 / 本地 Ollama
```

核心不是点对点翻译 6 条单向路径，而是 **一个统一的中间表示 IR + 三套 adapter**。同格式直通零翻译，异格式经 IR 桥接，流式和非流式都走同一套模型。

详细 3x3 翻译矩阵、API 映射表、流式状态机设计见 [docs/DESIGN.md](./docs/DESIGN.md) §8.3。

### 2.2 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12+ · FastAPI · SQLAlchemy 2.x async · aiosqlite · httpx · Typer |
| 前端 | React · TypeScript · Vite · Tailwind · shadcn/ui |
| 桌面外壳 | Tauri 2.x (Rust) |
| 包管理 | uv (Python) · bun (前端 / Tauri workspace) |
| 打包 | PyInstaller 单 exe，作为 Tauri sidecar 分发 |
| 平台 | Windows 优先，支持跨平台 |

---

## 3. 快速开始

### 3.1 安装依赖

```bash
uv sync
```

前端依赖在对应 workspace 内安装:

```bash
cd packages/app
bun install
```

### 3.2 启动本地服务

```bash
uv run python -m rosetta.server
```

默认监听 `127.0.0.1:1687`，并写入 `~/.rosetta/endpoint.json` 供 CLI / SDK 自动发现。

需要固定端口或暴露给局域网时:

```bash
uv run python -m rosetta.server --host 0.0.0.0 -p 8090
```

注意: server 当前没有 API-level auth。监听 `0.0.0.0` 后，局域网内其他机器可能使用你配置的 upstream key，请只在受信任网络下使用。

### 3.3 启动 Web 管理台

```bash
cd packages/app
bun run dev
```

Vite 会动态代理 `/admin` 和 `/v1` 到本地 Rosetta server。

### 3.4 最小链路自测

```bash
uv run rosetta upstream restore-mock
uv run rosetta chat --upstream mock "hello"
```

---

## 4. CLI 使用

### 4.1 Chat

```bash
# 显式指定 upstream(最稳妥)
uv run rosetta chat --upstream 00000000000000000000000000000000 "hello"

# 不传 --upstream 时必须传 --model,server 会按 model 匹配 upstream
uv run rosetta chat --model claude-haiku-4-5 "hello"

# 绕 server 直连上游(direct 模式)
uv run rosetta chat --base-url https://api.anthropic.com --api-key sk-ant-XXX --model claude-haiku-4-5 "hello"
```

`uv run rosetta chat "hello"` 不带 `--upstream` 也不带 `--model` 时没有路由信息,server 会返回 `missing_routing_info`。

Raw 调试会打印实际 request 和 SSE response frames。输出可能包含 `x-api-key` / `authorization` 等敏感字段，不要贴到公开位置。

```bash
uv run rosetta chat --raw "hello"
uv run rosetta chat --raw --raw-edge 20 "hello"
uv run rosetta chat --raw --raw-full "hello"
uv run rosetta chat --raw
```

REPL 支持 slash 命令自动补全，输入 `/` 或命令参数时可用上下键选择候选。

```text
/server_api <api_type>  切换 API 格式(messages|completions|responses)
/model <name>           切换模型
/model clear            切回 auto，走 upstream.model 兜底
/raw on|off             切换 raw request/response 输出
/raw_edge <n>           raw 模式显示前/后 n 条 SSE frame
/raw_step <n>           保留配置；CLI 当前不交互展开，完整输出用 --raw-full
/server_api、/model、/raw、/raw_edge、/raw_step 不带参数时显示当前配置
```

### 4.2 Upstream

`--base-url` 填上游 API 前缀，可以带网关路径或 `/v1`，不要填完整 endpoint。Rosetta 会按 upstream native API 自动追加固定路径:

- `messages`: `/v1/messages`
- `completions`: `/v1/chat/completions`
- `responses`: `/v1/responses`

```bash
uv run rosetta upstream add --name anthropic-main --native-api messages --api-key sk-ant-XXX --base-url https://api.anthropic.com --model claude-haiku-4-5  # --model 必填
uv run rosetta upstream update <id> --model claude-sonnet-4-5
uv run rosetta upstream test <id>
uv run rosetta model list
uv run rosetta upstream default <upstream-id>
uv run rosetta upstream defaults
```

### 4.3 本机客户端配置

`rosetta setup` 用于预览、写入或清理 Codex / Claude / OpenCode 的本机配置文件。

```bash
uv run rosetta setup preview codex --model <model>
uv run rosetta setup apply codex --model <model>
uv run rosetta setup clear codex --yes
```

输出或复制 Setup 页同款 PowerShell / export / CLI 命令:

```bash
uv run rosetta setup command codex --model <model> --kind powershell
uv run rosetta setup command codex --model <model> --kind export --copy
uv run rosetta setup command codex --kind cli
```

`codex` 可替换为 `claude` 或 `opencode`。Setup 使用 `models.alias` 写入客户端配置里的模型名；模型别名通过 Web 的 Upstreams 模型表或 `rosetta model alias <model> <alias>` 设置。旧的 `setup:<target>:<alias>` 路由映射已废弃。

### 4.4 Logs

```bash
uv run rosetta logs
uv run rosetta logs -f
uv run rosetta logs --upstream mock --limit 20
uv run rosetta logs config
uv run rosetta logs config --log-content summary --page-size 50
```

---

## 5. Web 和桌面开发

### 5.1 Web 管理台

```bash
# 终端 1
uv run python -m rosetta.server

# 终端 2
cd packages/app
bun install
bun run dev
```

GUI Chat 页要点:

- Nice 模式: 普通聊天气泡 + 流式文本
- Raw 模式: 用户气泡显示发送 request，模型气泡显示返回 SSE frame
- Raw response 默认显示前/后 N 条 frame，中间隐藏；Edge / Step 配置会记住
- Parse JSON 可把 raw SSE data 解析成 JSON 展示

### 5.2 桌面壳

```bash
uv run --group build python scripts/build.py --target server --sync-sidecar
cd packages/desktop
bun install
bun run dev
```

---

## 6. 开发检查和依赖维护

### 6.1 常用检查

```bash
# Python tests
uv run pytest

# Lint + format
uv run ruff check . --fix
uv run ruff format .

# 提交前检查
uv run ruff check .
uv run ruff format --check .
uv run pyright .
uv run pytest

# 前端检查
cd packages/app
npm run typecheck
npm run build
```

### 6.2 更新单个开发工具依赖

当 `uv run pyright .` 提示 pyright 有新版时，只升级 pyright 并重新验证:

```bash
uv lock --upgrade-package pyright
uv run pyright .
```

这会更新 `uv.lock` 里的 pyright 版本和 hash，不会改业务代码。

### 6.3 Lockfile

```bash
bun install --frozen-lockfile
# npm install
```

---

## 7. 版本和发布

### 7.1 基本约定

1. 主分支为 `main`。
2. 功能改动建议按主题拆分提交，避免把后端、前端、文档和测试揉成一笔。
3. 发布提交应只包含版本号、锁文件、发布说明或必要的构建配置变更；不要把未完成的功能改动混进发布提交。
4. `tag create` 只负责给当前提交打版本标记，不会自动打包；打包需显式执行 `build`。

### 7.2 版本号维护

版本号不要手改多个文件，统一用发布脚本维护。

```bash
# 检查各处版本号是否一致
uv run python scripts/publish.py check

# 显式改到指定版本
uv run python scripts/publish.py bump 0.1.1

# 按语义版本递增
uv run python scripts/publish.py bump patch
uv run python scripts/publish.py bump minor
uv run python scripts/publish.py bump major
```

版本递增建议:

- `patch`: bug fix、文档、内部实现优化，不改变用户可见接口。
- `minor`: 新增命令、页面能力、配置项或兼容性功能。
- `major`: 破坏性 CLI/API/配置变更。

`scripts/publish.py bump ...` 会同步更新:

- `pyproject.toml`
- `rosetta/__init__.py`
- `package.json`
- `packages/app/package.json`
- `packages/desktop/package.json`
- `packages/desktop/tauri/Cargo.toml`
- `packages/desktop/tauri/tauri.conf.json`

### 7.3 发布前检查

发布前至少跑一遍基础验证:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright .
uv run pytest
cd packages/app
npm run typecheck
npm run build
```

如果刚升级过 Python 开发工具依赖，例如 pyright，先确认锁文件已更新并通过类型检查:

```bash
uv lock --upgrade-package pyright
uv run pyright .
```

### 7.4 构建发布产物

```bash
# 构建发布目录
uv run python scripts/publish.py build

# 构建发布目录 + installer
uv run python scripts/publish.py build --installer
```

发布脚本产物在 `dist/rosetta-<version>/`。仅需要 Python 可执行文件时，可以走第 8 节的 `scripts/build.py` 命令。

### 7.5 推荐发布顺序

1. 确认工作区没有无关改动: `git status --short`
2. 更新版本: `uv run python scripts/publish.py bump patch|minor|major|<version>`
3. 运行第 7.3 节验证命令
4. 如需产物，运行 `uv run python scripts/publish.py build` 或 `uv run python scripts/publish.py build --installer`
5. 提交版本改动
6. 给当前提交打 tag
7. 推送分支和 tag

### 7.6 Tag 操作

```bash
# 本地创建 tag
uv run python scripts/publish.py tag create

# 创建并推送 tag
uv run python scripts/publish.py tag create --push

# 单独推送已有 tag
uv run python scripts/publish.py tag push

# 删除本地 tag
uv run python scripts/publish.py tag delete

# 删除本地 + 远端 tag
uv run python scripts/publish.py tag delete --push

# 仅删除远端 tag
uv run python scripts/publish.py tag delete --remote
```

Tag 应指向已经通过验证的发布提交。需要重新打 tag 时，先确认对应远端 tag 是否已发布给其他人，避免破坏已有发布引用。

---
## 8. 打包

### 8.1 常用命令

```bash
# 发布脚本打包
uv run python scripts/publish.py build
uv run python scripts/publish.py build --installer

# 仅构建 Python 可执行文件
uv run --group build python scripts/build.py

# 仅构建 server sidecar
uv run --group build python scripts/build.py --target server --sync-sidecar
```

### 8.2 产物位置

1. 发布脚本产物在 `dist/rosetta-<version>/`
2. 仅 PyInstaller 产物在 `dist/`
3. Tauri 桌面端产物在 `packages/desktop` 对应的构建输出目录

---

## 9. 文档索引

| 文件 | 作用 |
|---|---|
| [docs/DESIGN.md](./docs/DESIGN.md) | 架构真源，解释为什么这么设计 |
| [docs/FEATURE.md](./docs/FEATURE.md) | v0 分步任务清单 |
| [docs/ROADMAP.md](./docs/ROADMAP.md) | v1+ 后续方向 |
| [docs/setup/](./docs/setup/) | Codex / Claude / OpenCode 本机客户端 setup 指南 |
| [docs/guides/](./docs/guides/) | 工具链、打包、发布、数据库等专题指南 |
| [docs/archive/](./docs/archive/) | 已归档的设计备选和早期过程文档 |

---

## 10. License

TBD