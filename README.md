# Rosetta

> 本地跑的 LLM API 格式转换中枢 · Claude Messages / OpenAI Chat Completions / OpenAI Responses **三格式任意互译**

用 Claude Code 调 OpenAI 模型、用 OpenAI SDK 调 Claude 模型、在 Anthropic / OpenAI / OpenRouter / 国内中转站之间随意切换上游 —— **客户端只改 `base_url`,其他零侵入**。

---

## 能做什么

- **跨生态调用**:客户端用任一主流 API 格式写,上游可以是任一主流 LLM 服务,中间格式差异由代理透明翻译
- **多 upstream 集中管理**:一个地方管所有 key / 用量统计;客户端通过 `x-rosetta-upstream` header 显式选,或按入口 server_api 走 default upstream(支持 global fallback + per-server_api default,`rosetta upstream default <name>` 配置)
- **开箱即用**:CLI 一次性对话、REPL 多轮、桌面 GUI 三种交互,SSE 流式全程原生转发

**类比**:cc-switch 的"AI 配置管家"概念 + 自研的格式翻译引擎。cc-switch 切的是配置文件,本项目切的是运行时流量并做格式转换。

---

## 当前状态

**v0.2.3 · 核心链路已实现,持续打磨中**。

- 已落地:FastAPI 数据面 / 管理面、三 API 类型 IR 翻译、CLI/SDK、React 管理台、Tauri 桌面壳、PyInstaller 打包脚本
- 架构真源:见 [`docs/DESIGN.md`](./docs/DESIGN.md)
- 分阶段实施清单:[`docs/FEATURE.md`](./docs/FEATURE.md)

---

## 架构速览

```
┌─────────────┐        ┌─────────────────────┐        ┌──────────────────┐
│  客户端      │ ─────► │  rosetta (本机代理)  │ ─────► │  真实 LLM 服务    │
│  任一格式    │        │  三格式路由 + IR 翻译 │        │  任一 upstream   │
└─────────────┘        └─────────────────────┘        └──────────────────┘
     Claude SDK              127.0.0.1:<port>              api.anthropic.com
     OpenAI SDK              /v1/messages                  api.openai.com
     curl / fetch            /v1/chat/completions          openrouter.ai
                             /v1/responses                 自建中转站 / 本地 Ollama
```

**核心**:不是点对点翻译(6 条单向路径),而是 **一个统一的中间表示(IR)+ 三套 adapter**。同格式直通零翻译,异格式经 IR 桥接,流式和非流式都走。

详细 3×3 翻译矩阵、API 映射表、流式状态机设计见 [`docs/DESIGN.md`](./docs/DESIGN.md) §8.3。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12+ · FastAPI · SQLAlchemy 2.x async · aiosqlite · httpx · Typer |
| 前端 | React · TypeScript · Vite · Tailwind · shadcn/ui |
| 桌面外壳 | Tauri 2.x (Rust) |
| 包管理 | uv (Python) · bun (前端 / Tauri workspace) |
| 打包 | PyInstaller 单 exe(作为 Tauri sidecar 分发) |
| 平台 | Windows 优先,支持跨平台 |

---

## 开发

```bash
# 装依赖
uv sync

# 开发测试环境启动(推荐开多个终端)

# 终端 1:启动本地 server(写入 ~/.rosetta/endpoint.json)
uv run python -m rosetta.server

# 终端 2:启动 Web 管理台(Vite 会动态代理 /admin 和 /v1 到本地 server)
cd packages/app
bun install
bun run dev

# 终端 3:用 mock upstream 做最小链路自测
uv run rosetta upstream restore-mock
uv run rosetta chat --upstream mock "hello"

# 桌面壳开发模式(需要先准备 Tauri sidecar)
uv run --group build python scripts/build.py --target server --sync-sidecar
cd packages/desktop
bun install
bun run dev

# 起 server(默认 127.0.0.1 + 系统分配端口,客户端从 endpoint.json 发现)
uv run python -m rosetta.server

# 暴露给局域网 / 固定端口(⚠️ server 没有 auth 层,0.0.0.0 后局域网任何机器
# 都能用你配的 api_key 替你消费上游;请只在受信任网络下用)
uv run python -m rosetta.server --host 0.0.0.0 -p 8090

# 开箱即用:内置 mock upstream 无需任何 key,直接 echo 回复
uv run rosetta chat "hello"

# 想配真实上游:添 upstream 后按 name 选
# `--model` 可选,作为该 upstream 的默认模型;client body 不传 model 时由 server 兜底
# `--base-url` 填上游根地址,不要带 API 路径;rosetta 会按 upstream native API 自动追加
# /v1/messages、/v1/chat/completions 或 /v1/responses。
# 这些路径来自 api_types 字典表:messages=/v1/messages,completions=/v1/chat/completions,responses=/v1/responses。
# 例:填 https://api.example.com,不要填 https://api.example.com/v1
uv run rosetta upstream add --name anthropic-main --native-api messages --api-key sk-ant-XXX --base-url https://api.anthropic.com --model claude-haiku-4-5
uv run rosetta chat --upstream anthropic-main "hello"   # 不传 --model 也跑,用 upstream.model

# 改字段(部分更新;留空不动)
uv run rosetta upstream update <id> --model claude-sonnet-4-5

# 设为 global 默认上游;之后 chat 不传 --upstream 也能跑
uv run rosetta upstream default anthropic-main
uv run rosetta chat "hello"   # 不传 --upstream / --model,全靠 upstream 默认值

# 查看 global/messages/completions/responses 默认绑定
uv run rosetta upstream defaults

# 测一下当前 upstream 的 base_url / api_key / model 是否可用
uv run rosetta upstream test <id>

# 绕 server 直连(direct 模式)
uv run rosetta chat --base-url https://api.anthropic.com --api-key sk-ant-XXX --model claude-haiku-4-5 "hello"

# 误删 mock 后恢复
uv run rosetta upstream restore-mock

# 看请求日志
uv run rosetta logs              # 最近 N 条;默认条数走 logs config
uv run rosetta logs -f           # 实时 follow(Ctrl+C 退出)
uv run rosetta logs --upstream mock --limit 20
uv run rosetta logs config
uv run rosetta logs config --log-content summary --page-size 50

# 跑测试
uv run pytest

# Lint + 格式化
uv run ruff check . --fix
uv run ruff format .

# 提交前检查
uv run ruff check .
uv run ruff format --check .
uv run pyright .
uv run pytest
```

---

## 版本控制说明

- 主分支为 `main`
- 功能改动建议按主题拆分提交,避免把后端、前端、文档和测试揉成一笔
- 版本号不要手改多个文件,统一用发布脚本维护:
  - 校验当前版本是否一致:
    - `uv run python scripts/publish.py check`
  - 显式改到指定版本:
    - `uv run python scripts/publish.py bump 0.2.4`
  - 自动递增:
    - `uv run python scripts/publish.py bump patch`
    - `uv run python scripts/publish.py bump minor`
    - `uv run python scripts/publish.py bump major`
- `scripts/publish.py bump ...` 会同步更新这些位置的版本号:
  - `pyproject.toml`
  - `rosetta/__init__.py`
  - `package.json`
  - `packages/app/package.json`
  - `packages/desktop/package.json`
  - `packages/desktop/tauri/Cargo.toml`
  - `packages/desktop/tauri/tauri.conf.json`
- 版本号更新后,再按需提交并打 tag:
  - 本地创建 tag: `uv run python scripts/publish.py tag create`
  - 创建并推送 tag: `uv run python scripts/publish.py tag create --push`
- 提交前至少运行与改动面对应的验证:
  - Python lint: `uv run ruff check .`
  - Python format check: `uv run ruff format --check .`
  - Python type check: `uv run pyright .`
  - Python tests: `uv run pytest`
  - 前端: `cd packages/app && npm run typecheck && npm run build`

---

## 打包说明

- 一键走发布脚本,同时按当前版本号归集产物:
  - `uv run python scripts/publish.py build`
  - `uv run python scripts/publish.py build --installer`
- 构建 Python 可执行文件:
  - `uv run --group build python scripts/build.py`
- 仅构建 server sidecar:
  - `uv run --group build python scripts/build.py --target server --sync-sidecar`
- 构建产物位置:
  - 发布脚本产物在 `dist/rosetta-<version>/`
  - 仅 PyInstaller 产物在 `dist/`
  - Tauri 桌面端在 `packages/desktop` 对应的构建输出目录
- 桌面端打包前,先确保 sidecar 已同步,再执行:
  - `cd packages/desktop`
  - `bun install`
  - `bun run build` 或 `bun run tauri build`

---

## 文档索引

| 文件 | 作用 |
|---|---|
| [`docs/DESIGN.md`](./docs/DESIGN.md) | 架构真源(为什么这么设计) |
| [`docs/FEATURE.md`](./docs/FEATURE.md) | v0 分步任务清单(heading emoji 标进度) |
| [`docs/ROADMAP.md`](./docs/ROADMAP.md) | v1+ 后续方向(不在 v0 范围但值得做) |
| [`docs/archive/`](./docs/archive/) | 已归档的设计备选(TS 栈 / 多包布局 / 早期 PROCESS.md) |

---

## License

TBD
