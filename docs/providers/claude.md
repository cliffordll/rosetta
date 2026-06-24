# Claude 使用说明

> 请根据实际 Claude 客户端、模型和密钥管理方式替换内容。

## 1. 适用场景

当 Claude 客户端支持配置 Anthropic Messages endpoint 时，可以把 Rosetta 作为本地代理入口。

## 2. 使用说明

这是最关键的一步。你需要通过设置几个环境变量，告诉 Claude Code 去找本地的 Resotta 服务，而不是官方的云端 API。

### 2.1. 安装与卸载

安装：使用 Node.js 的包管理器 npm 进行全局安装。

```bash
npm install -g @anthropic-ai/claude-agent-sdk
```

卸载：使用 npm 卸载全局包，并可选择清理残留的配置文件夹。

```bash
npm uninstall -g @anthropic-ai/claude-agent-sdk
# 清理配置（可选）
rm -rf ~/.claude
```
### 2.2. 方法 A：临时配置

直接在终端里运行下面的命令，效果只对当前这个终端窗口有效。

powershell

```powershell
$env:ANTHROPIC_BASE_URL = "http://localhost:1687"
# 放在请求头 X-Api-Key 里。	最标准的方式。(Rosetta 使用该方式)
$env:ANTHROPIC_API_KEY = "sk-ant-your-key"
# 放在请求头 Authorization: Bearer <token> 里。	网关或代理服务要求 Bearer Token 认证时使用。
$env:ANTHROPIC_AUTH_TOKEN = "ollama"

$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "deepseek-v4-flash"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "deepseek-v4-flash"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "deepseek-v4-flash"
```

bash

```bash
export ANTHROPIC_BASE_URL="http://localhost:1687"
export ANTHROPIC_API_KEY="sk-ant-your-key" # 本地服务不验证，随便填
export ANTHROPIC_AUTH_TOKEN="ollama"

# 这几行特别重要：把 Claude Code 请求的模型名映射成你本地的模型名
export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-flash"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flashb"
export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-flash"
```

### 2.3. 方法 B：永久配置

在 Claude Code 的用户设置文件 ~/.claude/settings.json 里添加 "env" 字段，这样配置会一直生效。

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:1687",
    "ANTHROPIC_API_KEY": "sk-ant-your-key",
    "ANTHROPIC_AUTH_TOKEN": "ollama",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-flash"
  }
}
```

### 2.4. Claude 启动

```bash
claude
```

## 3. 注意事项

- Claude Messages 入口通常使用 `x-api-key` 鉴权头。
- Rosetta 会按入口协议读取客户端 API key；如果客户端传入 key，会覆盖 upstream 中保存的 key。
- upstream 的 `base_url` 填真实 Claude 上游根地址，不要带 `/v1/messages`。
