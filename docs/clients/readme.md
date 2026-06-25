# Rosetta 快速入门

> LLM API 格式转换中枢 —— Claude Messages / OpenAI Chat Completions / OpenAI Responses 三格式任意互译。

## 1. 启动 / 停止服务

```bash
# 启动 Rosetta 服务（默认 127.0.0.1:1687）
rosetta start

# 指定端口和 host
rosetta start --host 0.0.0.0 --port 8090

# 停止服务
rosetta stop

# 查看服务状态
rosetta status

# 用量汇总（today / week / month）
rosetta stats
rosetta stats week
rosetta stats month
```

## 2. 添加 Upstream

将真实 LLM 服务配置为 upstream 供客户端使用。支持三种 native API 格式：

| native_api | 对应路径 |
|---|---|
| `messages` | `/v1/messages`（Claude 格式） |
| `completions` | `/v1/chat/completions`（OpenAI Chat 格式） |
| `responses` | `/v1/responses`（OpenAI Responses 格式） |

```bash
# 添加 upstream
rosetta upstream add \
  --name gpt4o-upstream \
  --provider openai \
  --native-api responses \
  --base-url https://api.openai.com \
  --api-key sk-your-key \
  --model gpt-4o

# 测试连通性
rosetta upstream test <id>

# 查看所有 upstream
rosetta upstream list

# 恢复内置 mock upstream
rosetta upstream restore-mock
```

## 3. 配置默认模型

客户端不传 `r-upstream` header 时，Rosetta 按请求体中的 `model` 字段匹配 upstream。
同一个 model 对应多个 upstream 时，必须指定默认 upstream。

```bash
# 设置某个 model 的默认 upstream
rosetta upstream default gpt4o-upstream --model gpt-4o

# 查看所有默认映射
rosetta upstream defaults
```

## 4. 客户端配置

客户端只需修改 base_url 指向 Rosetta 地址（http://localhost:1687）。

- Codex: 参见 `rosetta guide codex`
- Claude: 参见 `rosetta guide claude`
- OpenCode: 参见 `rosetta guide opencode`
- README: 参见 `rosetta guide readme`

## 5. CLI 常用命令

```bash
# 全局帮助
rosetta --help
rosetta <command> --help

# 服务管理
rosetta start              # 启动服务
rosetta stop               # 停止服务
rosetta status             # 查看服务状态
rosetta stats              # today 用量汇总
rosetta stats week         # 本周用量汇总
rosetta stats month        # 本月用量汇总

# upstream 管理
rosetta upstream list                               # 列出所有
rosetta upstream add --help                         # 查看添加参数
rosetta upstream update <id> --name new-name        # 更新
rosetta upstream remove <id>                        # 删除
rosetta upstream default <name> --model <model>     # 设为默认
rosetta upstream defaults                           # 查看默认模型映射
rosetta upstream test <id>                          # 测试连通性
rosetta upstream restore-mock                       # 恢复内置 mock

# 聊天
rosetta chat --upstream <name> "你好"                # 一次性对话，指定 upstream
rosetta chat --model <name> --api-key sk-xxx "你好"  # 一次性对话，指定 model 和 api-key 
rosetta chat                                         # 进入 REPL 交互模式

# 日志
rosetta logs                                         # 最近日志
rosetta logs -f                                      # 实时追踪（Ctrl+C 退出）
rosetta logs --upstream <name> --limit 20            # 筛选
rosetta logs config --log-content summary            # 配置日志内容级别
rosetta logs config --page-size 50                   # 配置每页条数
rosetta logs clear --yes                             # 清空全部日志

# 配置说明
rosetta guide codex                         # Codex 说明
rosetta guide claude                        # Claude 说明
rosetta guide opencode                      # OpenCode 说明
rosetta guide readme                        # 本说明
```

## 6. 注意事项

- upstream 的 `base_url` 填真实 LLM 服务 API 前缀（如 `https://api.openai.com` 或 `https://api.openai.com/v1`），不要填 Rosetta 地址，不要填完整 endpoint。
- 客户端连接 Rosetta 时，base_url 设为 `http://localhost:1687`。
- 客户端传入 api-key 时会覆盖 upstream 中保存的 key。
- `rosetta start` 默认绑定 `127.0.0.1:1687`，暴露到局域网需显式 `--host 0.0.0.0`（无 auth 层，请在受信任网络下使用）。
- server 模式下 `--model` 和 `--api-key` 均可留空——留空 = 用 upstream 配置兜底；传 `none` 或 `""` 也等价于留空。
- direct 模式（`--base-url`）下 `--model` 和 `--api-key` 必填，`--upstream` 自动失效。
