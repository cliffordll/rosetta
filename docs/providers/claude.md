# Claude 使用说明

> 通过 Rosetta 让 Claude Code 使用任意 LLM 上游。

## 1. 启动 Rosetta

```bash
# 启动 Rosetta 服务（默认 127.0.0.1:1687）
rosetta start
```

或者用 python 直接启动：

```bash
uv run python -m rosetta.server
```

## 2. 添加 Upstream

将真实 LLM 服务配置为 upstream 供客户端使用。

```bash
# 添加一个 Anthropic upstream
rosetta upstream add \
  --name claude-upstream \
  --provider anthropic \
  --native-api messages \
  --base-url https://api.anthropic.com \
  --api-key sk-ant-your-key \
  --model claude-sonnet-4-20250514

# 查看所有 upstream
rosetta upstream list
```

## 3. 配置默认模型

```bash
rosetta upstream default claude-upstream --model claude-sonnet-4-20250514
```

## 4. Claude Code 客户端配置

通过环境变量让 Claude Code 指向 Rosetta。

### 4.1 临时配置

```bash
export ANTHROPIC_BASE_URL="http://localhost:1687"
export ANTHROPIC_API_KEY="sk-ant-your-key"
export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-4-20250514"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="claude-haiku-4-20250514"
export ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-4-20250514"
```

### 4.2 永久配置

在 `~/.claude/settings.json` 中：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:1687",
    "ANTHROPIC_API_KEY": "sk-ant-your-key",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-sonnet-4-20250514",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-20250514",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-20250514"
  }
}
```

### 4.3 启动

```bash
claude
```

## 5. CLI 常用命令

```bash
# 查看帮助
rosetta --help

# upstream 管理
rosetta upstream list                               # 列出所有 upstream
rosetta upstream add --help                         # 查看添加参数
rosetta upstream update <id> --name new-name        # 更新
rosetta upstream remove <id>                        # 删除
rosetta upstream default <name> --model <model>     # 设为默认
rosetta upstream defaults                           # 查看默认映射
rosetta upstream test <id>                          # 测试连通性
rosetta upstream restore-mock                       # 恢复内置 mock

# 聊天
rosetta chat "你好"                                  # 用默认 upstream 对话
rosetta chat --upstream <name> "你好"                # 指定 upstream
rosetta chat --raw "你好"                            # 查看原始 request/response

# 日志
rosetta logs                                         # 最近日志
rosetta logs -f                                      # 实时追踪
rosetta logs --upstream <name> --limit 20            # 筛选

# 查看配置说明
rosetta upstream guide codex                         # Codex 说明
rosetta upstream guide claude                        # 本说明
rosetta upstream guide readme                        # 快速入门
```

## 6. 注意事项

- upstream 的 `base_url` 填真实 LLM 服务地址（如 https://api.anthropic.com），不要带路径。
- 客户端连接 Rosetta 时，base_url 设为 `http://localhost:1687`。
- Claude Messages 入口使用 `x-api-key` 鉴权头。
- 客户端传入 api-key 时会覆盖 upstream 中保存的 key。
