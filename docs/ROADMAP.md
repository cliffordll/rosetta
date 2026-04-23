# Rosetta v1+ 路线图

v0 已落地的范围见 `docs/FEATURE.md`(阶段 0~8 ✅/🟡 全走完)。
本文档记录**不在 v0 范围但值得做**的方向,定期回顾优先级。

> 迁移自 `FEATURE.md` 附录 B(2026-04)。v0 验收闭环后,后续规划不再与 v0
> 任务清单混写,避免"已完成 / 规划中"在同一张表里产生歧义。

---

## 数据面体验

- **Chat 会话持久化** —— 新增 `conversations` / `messages` 表 +
  `/admin/conversations/*` 端点 + GUI 侧栏会话列表、历史翻阅、会话导出。
  v0 Chat 页只在内存保留,v1 升级为真的能翻旧对话。
- **Chat 原始请求/响应预览面板** —— Chat 页可折叠 JSON 面板,显示每轮请求
  体 + 响应体(含 SSE 完整事件序列)。翻译器 / 状态机 bug 的最快排查工具。
- **CLI Chat 增强** —— 多会话文件(`rosetta chat --session foo`,
  `~/.rosetta/sessions/*.json`)、会话导入导出、tools 交互(显示 tool_use、
  允许手填 tool_result 继续)。

## 翻译与协议

- 翻译层健壮性打磨(多模态 / 罕见 `tool_choice` 组合 / 边缘字段回写)
- Responses API 有状态特性完整支持(`previous_response_id` 跨翻译、
  background jobs)
- 模型别名 / 虚拟模型(把 `gpt-5` 别名到 Anthropic 上游的 `claude-4.5`)
- 流式 latency / tokens 字段补齐(v0 的 Forwarder 流式 latency 只到"请求
  分发到 Response 构造",tokens 写 NULL;v1 在流尾 drain 时聚合补上)

## 管理面体验

- 实时日志流(SSE / WebSocket 而非 polling)
- Upstream PUT / DELETE + connectivity test(`POST /admin/upstreams/{id}/test`)
- 路由规则拖拽排序(若引入 routes 表;v0 已砍,等真实需求回归再做)
- 用量统计(按 key / upstream / model 切分,时间序列图)

## 发版与分发

- **自动更新真实启用**(v0 代码已合入 tauri-plugin-updater,但 pubkey 占位
  未替换、`tauri signer generate` 的密钥未入 GH secrets;见 FEATURE §8.2 🟡)
- **代码签名**(v0 留了 GH secrets 槽位,等采购 Authenticode / Apple
  Developer 证书;见 FEATURE §8.3 🟡)
- 跨平台打包(macOS / Linux);`rosetta-server.spec` 目前仅 Windows 验证
- 首个 Release 闭环(tag → CI → 签名 installer → latest.json → updater)

## 运维 / 扩展

- 配置导入导出(`rosetta config export/import`,便于多机同步)
- 请求日志 TTL 清理策略
- 多用户账户(多台机器共享一个 server 实例)
- 多语言(i18n)
