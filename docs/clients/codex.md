# Codex 使用说明

> 请根据实际 Codex 客户端、模型和密钥管理方式替换内容。

## 1. 适用场景

当 Codex 客户端支持配置 OpenAI-compatible endpoint 时，可以把 Rosetta 作为本地代理入口。
Codex 连接 Rosetta，Rosetta 再按 upstream 的 `native_api` 转发或翻译到真实上游。

## 2. 使用说明

Rosetta 服务启动和 upstream 添加参见 `rosetta guide readme`。这里仅说明 Codex 客户端侧配置。

### 2.1. 安装与卸载

安装：使用 Node.js 的包管理器 npm 进行全局安装。

```bash
npm install -g @openai/codex
```

卸载：使用 npm 卸载全局包，并可选择清理用户配置。

```bash
npm uninstall -g @openai/codex
# 清理配置（可选）
rm -rf ~/.codex
```

### 2.2. Codex 配置

修改 Codex 配置文件：`~/.codex/config.toml`。

```toml
model = "deepseek-v4-flash"
model_provider = "rosetta"

# 给模型指定真实上下文，上下文窗口应该远大于压缩阈值，才能保证长对话的稳定运行。
# 上下文窗口设为1,047,576，压缩阈值设为105,197；也有设为1,000,000和900,000的组合。
# 解决报错：stream disconnected before completion: stream closed before response.completed。
model_context_window = 1047576
model_auto_compact_token_limit = 105197

[model_providers.rosetta]
name = "Rosetta"
# 配置 Rosetta API地址
base_url = "http://localhost:1687"
# 指定从哪个环境变量读取 API Key
env_key = "OPENAI_API_KEY"

# 根据模型选择 'chat' 或 'responses'，一些新模型需要 'responses'。Codex 需要使用 Rosetta /v1/responses 接口
# 走 Rosetta Responses 入口时填 responses；走 Chat Completions 入口时填 chat。
wire_api = "responses"

# 是 Codex 配置中用来临时绕过 HTTPS 安全验证的开关；仅在本地 HTTP 或自签名 HTTPS 调试时使用。
allow_insecure = true
```

这里的关键点：

- `base_url` 指向本地 Rosetta server：`http://localhost:1687`。
- `wire_api = "responses"` 时，Codex 请求 Rosetta `/v1/responses`。
- `wire_api = "chat"` 时，Codex 请求 Rosetta `/v1/chat/completions`。
- `model` 要和你希望 Codex 发送的模型名一致；Rosetta 可按该 model 匹配 upstream。

### 2.3. 环境变量

powershell

```powershell
# $env:OPENAI_BASE_URL="https://your-custom-endpoint.com/"
$env:OPENAI_API_KEY="sk-your-key"
```

bash

```bash
# export OPENAI_BASE_URL="https://your-custom-endpoint.com/"
export OPENAI_API_KEY="sk-your-key"
```

Rosetta 本地 server 默认不验证这个 key；如果 Codex 传入 API key，Rosetta 会把它当作上游 key override。不想覆盖 upstream 中保存的 key 时，可以填一个占位值，并依赖 Rosetta upstream 的 `api_key`。

### 2.4. 客户端使用说明

```bash
codex --oss --local-provider rosetta
```

## 3. 注意事项

- Codex 连接 Rosetta 时，`base_url` 使用本地 Rosetta server 地址。
- 不要把 Rosetta 地址填到 upstream 的 `base_url`；upstream 指真实上游 API 前缀。
- Codex 的 `wire_api` 决定 Rosetta 入口格式；upstream 的 `native_api` 决定 Rosetta 转发到真实上游时使用的格式。
- Rosetta 会按入口协议读取客户端 API key；如果客户端传入 key，会覆盖 upstream 中保存的 key。