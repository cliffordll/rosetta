# Rosetta 快速入门

> LLM API 格式转换中枢 — Claude Messages / OpenAI Chat Completions / OpenAI Responses 三格式任意互译

## 安装

```bash
uv sync
```

## 启动服务

```bash
# 终端 1:启动 server
uv run python -m rosetta.server

# 终端 2:启动 Web 管理台
cd packages/app
bun install
bun run dev
```

## CLI 快速上手

```bash
# 内置 mock upstream,无需任何 key
uv run rosetta chat "hello"

# 添加真实 upstream
uv run rosetta upstream add \
  --name anthropic-main \
  --native-api messages \
  --api-key sk-ant-XXX \
  --base-url https://api.anthropic.com \
  --model claude-haiku-4-5

# 设为默认 upstream
uv run rosetta upstream default anthropic-main

# CLI 对话
uv run rosetta chat "你好"
```

## 客户端配置

客户端只需修改 base_url 指向 Rosetta 地址（默认 http://127.0.0.1:1687），
其他零侵入。详见 `rosetta upstream guide codex` 或 `rosetta upstream guide claude`。

## 更多

- 完整文档: docs/ 目录
- 架构设计: docs/DESIGN.md
