# Codex 使用说明

> 请根据实际 Codex 客户端、模型和密钥管理方式替换内容。

## 1. 适用场景

当 Codex 客户端支持配置 OpenAI-compatible endpoint 时，可以把 Rosetta 作为本地代理入口。

## 2. 使用说明

### 2.1. 安装与卸载

安装：使用 Node.js 的包管理器 npm 进行全局安装。

```bash
npm install -g @openai/codex
```

卸载：使用 npm 卸载全局包，并可选择清理残留的配置文件夹。

```bash
npm uninstall -g @openai/codex
# 清理配置（可选）
rm -rf ~/.codex
```

### 2.2. 环境配置说明

修改 Codex 配置文件：打开 ~/.codex/config.toml，按照下面的示例调整，关键是把 wire_api 改成 "responses"。

```toml
# 给模型指定真实上下文，上下文窗口应该远大于压缩阈值，才能保证长对话的稳定运行。
# 上下文窗口设为1,047,576，压缩阈值设为105,197；也有设为1,000,000和900,000的组合。
# 解决报错：stream disconnected before completion: stream closed before response.completed。
model_context_window = 1047576
model_auto_compact_token_limit = 105197

model = "deepseek-v4-flash"
model_provider = "ds_provider" 

[model_providers.ds_provider]
name = "DS API"
# 配置 Rosetta API地址
base_url = "http://localhost:1687"
# 指定从哪个环境变量读取 API Key
env_key = "OPENAI_API_KEY"
# 根据模型选择 'chat' 或 'responses'，一些新模型需要 'responses'。Codex 需要使用 Rosetta /v1/responses 接口
wire_api = "responses"

model = "deepseek-v4-flash"
# 是 Codex 配置中用来临时绕过 HTTPS 安全验证的开关
allow_insecure = true

[model_providers.my_provider]
......
```

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

### 2.3. 客户端使用说明

```bash
codex --oss --local-provider ds_provider
```

## 3. 注意事项

- 不要把 upstream 的 `base_url` 填成 Rosetta 地址；upstream 指真实上游根地址。
- 客户端连接 Rosetta 时，base URL 使用本地 Rosetta server 地址。
- 如果客户端传入 API key，Rosetta 会优先使用客户端 key 覆盖 upstream 中保存的 key。
