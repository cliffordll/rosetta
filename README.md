# Rosetta

> 本地跑的 LLM API 格式转换中枢 · Claude Messages / OpenAI Chat Completions / OpenAI Responses **三格式任意互译**

用 Claude Code 调 OpenAI 模型、用 OpenAI SDK 调 Claude 模型、在 Anthropic / OpenAI / OpenRouter / 国内中转站之间随意切换上游 —— **客户端只改 `base_url`,其他零侵入**。

---

## 能做什么

- **跨生态调用**:客户端用任一主流 API 格式写,上游可以是任一主流 LLM 服务,中间格式差异由代理透明翻译
- **多 upstream 集中管理**:一个地方管所有 key / 用量统计;客户端通过 `x-rosetta-upstream` header 显式选择上游
- **开箱即用**:CLI 一次性对话、REPL 多轮、桌面 GUI 三种交互,SSE 流式全程原生转发

**类比**:cc-switch 的"AI 配置管家"概念 + 自研的格式翻译引擎。cc-switch 切的是配置文件,本项目切的是运行时流量并做格式转换。

---

## 当前状态

**pre-v0 · 设计评审中,未开始编码**。

- 架构已定稿:见 [`docs/DESIGN.md`](./docs/DESIGN.md)
- 分阶段实施清单:[`docs/FEATURE.md`](./docs/FEATURE.md)(v0 共 8 阶段 30 步 · heading emoji 标进度,预估 13-20 人日)

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

详细 3×3 翻译矩阵、协议映射表、流式状态机设计见 [`docs/DESIGN.md`](./docs/DESIGN.md) §8.3。

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

> 代码尚未开始编写。下列命令是 v0 目标形态,阶段 0-1 落地后生效。

```bash
# 装依赖
uv sync

# 起 server
uv run python -m rosetta.server

# 添 upstream
uv run rosetta upstream add --name anthropic-main --protocol messages --api-key sk-ant-XXX

# 跑 chat(必须指定 upstream)
uv run rosetta chat --upstream anthropic-main --model claude-haiku-4-5 "hello"

# 跑测试
uv run pytest

# Lint + 格式化
uv run ruff check . --fix
uv run ruff format .
```

---

## 文档索引

| 文件 | 作用 |
|---|---|
| [`docs/DESIGN.md`](./docs/DESIGN.md) | 架构真源(为什么这么设计) |
| [`docs/FEATURE.md`](./docs/FEATURE.md) | v0 分步任务清单 + v1+ 规划 + 节奏建议(heading emoji 标进度) |
| [`docs/archive/`](./docs/archive/) | 已归档的设计备选(TS 栈 / 多包布局 / 早期 PROCESS.md) |
| [`CLAUDE.md`](./CLAUDE.md) | Claude 会话协作约定(项目级) |

---

## 协作约定

项目使用 Claude Code 辅助开发。协作规范、命名约定、目录权限等见 [`CLAUDE.md`](./CLAUDE.md),任何 Claude 会话在本仓库内工作时需先阅读该文件。

---

## License

TBD
