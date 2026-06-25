# OpenCode 使用说明

> 请根据实际 OpenCode 客户端、模型和密钥管理方式替换内容。

## 1. 适用场景

当 OpenCode 通过 OpenAI-compatible provider 访问模型时，可以把 Rosetta 作为本地代理入口。
OpenCode 连接 Rosetta，Rosetta 再按 upstream 的 `native_api` 转发或翻译到真实上游。

## 2. 使用说明

Rosetta 服务启动和 upstream 添加参见 `rosetta guide readme`。这里仅说明 OpenCode 客户端侧配置。

### 2.1. 安装与卸载

安装：OpenCode 支持多种安装方式，Node.js 环境下可以使用 npm 全局安装。

```bash
npm install -g opencode-ai
```

卸载：使用 npm 卸载全局包，并可选择清理用户配置。

```bash
npm uninstall -g opencode-ai
# 清理配置（可选）
rm -rf ~/.config/opencode
```

Windows 也可以使用 npm 安装；如果需要更完整的终端兼容性，优先在 WSL 中使用。

### 2.2. OpenCode 配置

修改 OpenCode 全局配置文件：`~/.config/opencode/opencode.json`。

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "rosetta/deepseek-v4-flash",
  "small_model": "rosetta/deepseek-v4-flash",
  "provider": {
    "rosetta": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Rosetta",
      "options": {
        "baseURL": "http://localhost:1687/v1",
        "apiKey": "{env:OPENAI_API_KEY}"
      },
      "models": {
        "deepseek-v4-flash": {
          "name": "deepseek-v4-flash"
        }
      }
    }
  }
}
```

这里的关键点：

- `model` 使用 `<provider-id>/<model-id>`，上例是 `rosetta/deepseek-v4-flash`。
- `provider.rosetta.npm` 使用 `@ai-sdk/openai-compatible`，让 OpenCode 发送 OpenAI-compatible 请求。
- `options.baseURL` 指向 Rosetta 的 OpenAI-compatible 前缀：`http://localhost:1687/v1`。
- `models` 里的模型 id 要和你希望 OpenCode 发送的 `model` 一致；Rosetta 可按该 model 匹配 upstream。

### 2.3. 环境变量

powershell

```powershell
$env:OPENAI_API_KEY="sk-your-key"
```

bash

```bash
export OPENAI_API_KEY="sk-your-key"
```

Rosetta 本地 server 默认不验证这个 key；如果 OpenCode 传入 API key，Rosetta 会把它当作上游 key override。不想覆盖 upstream 中保存的 key 时，可以填一个占位值，并依赖 Rosetta upstream 的 `api_key`。

### 2.4. 客户端使用说明

进入项目目录后启动 OpenCode：

```bash
opencode
```

也可以直接执行一次性任务：

```bash
opencode run "解释这个项目的入口结构"
```

## 3. 注意事项

- OpenCode 连接 Rosetta 时，`baseURL` 建议写 `http://localhost:1687/v1`。
- 不要把 Rosetta 地址填到 upstream 的 `base_url`；upstream 指真实上游 API 前缀。
- OpenCode 的 `@ai-sdk/openai-compatible` provider 默认适合 `/v1/chat/completions` 入口。
- 如果需要 OpenCode 使用 `/v1/responses` 类入口，需使用 OpenCode 支持 Responses 的 provider 配置，并让请求打到 Rosetta `/v1/responses`。
- Rosetta 会按入口协议读取客户端 API key；如果客户端传入 key，会覆盖 upstream 中保存的 key。