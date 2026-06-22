# Rosetta 快速入门

> LLM API 格式转换中枢 —— Claude Messages / OpenAI Chat Completions / OpenAI Responses 三格式任意互译。

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
# 添加一个 OpenAI upstream
rosetta upstream add \
  --name gpt4o-upstream \
  --provider openai \
  --native-api responses \
  --base-url https://api.openai.com \
  --api-key sk-your-key \
  --model gpt-4o

# 添加一个 Ollama 本地模型
rosetta upstream add \
  --name ollama-deepseek \
  --provider ollama \
  --native-api completions \
  --base-url http://localhost:11434 \
  --model deepseek-r1

# 查看所有 upstream
rosetta upstream list
```

## 3. 配置默认模型

客户端不传 r-upstream header 时，Rosetta 按请求体中的 model 字段匹配 upstream。

```bash
# 将某个 upstream 设为 model 的默认路由
rosetta upstream default gpt4o-upstream --model gpt-4o

# 查看默认映射
rosetta upstream defaults
```

## 4. 客户端配置

客户端只需修改 base_url 指向 Rosetta 地址。

- Codex: 参见 `rosetta upstream guide codex`
- Claude: 参见 `rosetta upstream guide claude`

```bash
# Rosetta 服务地址
http://localhost:1687
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
rosetta upstream guide claude                        # Claude 说明
rosetta upstream guide readme                        # 本说明
```

## 6. 注意事项

- upstream 的 base_url 填真实 LLM 服务地址，不要填 Rosetta 地址。
- 客户端连接 Rosetta 时，base_url 设为 http://localhost:1687。
- 客户端传入 api-key 时会覆盖 upstream 中保存的 key。
