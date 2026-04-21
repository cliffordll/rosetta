# Rosetta 开发任务清单(FEATURE)

> **文件定位**:静态任务定义。"要做什么 / 验收标准"。
>
> 配套三文件:
> - [`DESIGN.md`](./DESIGN.md) — 架构真源(为什么这么设计)
> - `FEATURE.md` — 任务清单(本文件 · 做什么)
> - [`PROCESS.md`](./PROCESS.md) — 执行日志(做到哪 · append-only)
>
> **使用方式**:按步骤顺序执行,每步完成后:
> 1. 按"手动测试步骤"逐条执行
> 2. 对照"预期结果"核查每条输出
> 3. 在 `PROCESS.md` 末尾追加一条步骤记录(产出、验证结果、时间戳)
> 4. 明确向用户请求确认
> 5. 得到"通过" / "继续"回复后才进入下一步
>
> **本文件原则上不动**;如果步骤定义需要调整,在 `PROCESS.md` 里留变更记录,再回头修这里。

---

## 字段含义

| 字段 | 说明 |
|---|---|
| **目标** | 这一步要完成什么 |
| **产出** | 具体会新增 / 修改的文件 |
| **手动测试步骤** | 编号动作,一条一条告诉你"怎么做" |
| **预期结果** | 每步动作对应的具体输出 / 可观察现象 |
| **通过判据** | 一行话说明这步完成的标志 |
| **风险** | 可能踩的坑 |

---

## 阶段 0 · 仓库与环境(0.5-1 天)

### 步骤 0.1 · Python 工程骨架

- **目标**:建立 `rosetta` 单包的目录骨架 + uv 环境
- **产出**:
  - `pyproject.toml`(uv 驱动,`[project.scripts]` 注册 `rosetta` / `rosetta-server`)
  - `rosetta/` 根包 + `server/` / `sdk/` / `cli/` / `shared/` 四个子包(均含 `__init__.py`)
  - `.python-version`(钉 Python 版本)
  - `uv.lock`
- **手动测试步骤**:
  1. 项目根跑 `uv sync`
  2. 跑 `uv run python -c "import rosetta; print(rosetta.__file__)"`
  3. 跑 `uv run python -c "from rosetta import server, sdk, cli, shared; print('ok')"`
- **预期结果**:
  - 步骤 1:终端出现 `Resolved N packages` / `Installed N packages`,无红色报错,项目根多出 `.venv/` 和 `uv.lock`
  - 步骤 2:打印形如 `D:\opendemo\claudedemo\rosetta\rosetta\__init__.py`
  - 步骤 3:打印 `ok`
- **通过判据**:三条命令 exit code 均为 0,输出如上
- **风险**:import 名 `rosetta` 和 PyPI 包名可能冲突;若打算发布用 distribution 名 `rosetta-proxy`,import 名保持 `rosetta`

### 步骤 0.2 · Lint / 类型 / 测试基建

- **目标**:静态检查 + 测试框架就位,后续每阶段都能 CI
- **产出**:
  - `ruff.toml`(format + lint 配置)
  - `pyrightconfig.json` 或 `mypy.ini`(strict 模式 + Pydantic 插件)
  - `tests/` 目录 + `pytest.ini`(asyncio 模式)
  - `tests/test_smoke.py`(1 个 trivial 测试,断言 `import rosetta` 能工作)
- **手动测试步骤**:
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run mypy rosetta/`(或 `uv run pyright rosetta/`)
  4. `uv run pytest`
- **预期结果**:
  - 步骤 1:`All checks passed!`,无红色 diag
  - 步骤 2:`N files already formatted`,无 diff
  - 步骤 3:`Success: no issues found in N source files`
  - 步骤 4:`1 passed in Xs`
- **通过判据**:四条命令 exit code 均为 0
- **风险**:mypy / pyright 的 async 支持差异;先上 strict,跑得动再说

### 步骤 0.3 · 基础 CI(GitHub Actions)

- **目标**:push 时自动跑 lint + test(在 GitHub 云上,不在本地)
- **产出**:
  - `.github/workflows/ci.yml`(matrix:windows-latest 为主,ubuntu-latest 陪跑)
- **手动测试步骤**:
  1. 新建临时分支 `ci-test`,随便改一行文件(比如 README 加个空格)
  2. `git add . && git commit -m "test: trigger ci" && git push origin ci-test`
  3. 打开 GitHub 仓库 Actions 标签页
  4. 等 workflow 跑完(1-3 分钟)
  5. 收尾:`git checkout main && git branch -D ci-test && git push origin --delete ci-test`
- **预期结果**:
  - 步骤 3-4:看到最新 run,其中 job 包含 `ruff check` / `ruff format --check` / `mypy` / `pytest`,每个都是绿勾
- **通过判据**:GitHub Actions 页面最新 run 状态为 ✅;失败则点进红叉 job 查 log 修到绿
- **风险**:Windows runner 装 uv 的方式 — 用官方 `astral-sh/setup-uv@v3`

---

## 阶段 1 · Server 骨架 + 三格式直通(1.5-2 天)

### 步骤 1.1 · FastAPI app + admin 心跳

- **目标**:能起 HTTP 服务,只暴露最小 admin 端点
- **产出**:
  - `rosetta/server/app.py`(FastAPI app 工厂)
  - `rosetta/server/admin/__init__.py`(router)
  - `rosetta/server/admin/health.py`:`GET /admin/ping` + `GET /admin/status`
  - `rosetta/server/__main__.py`(`python -m rosetta.server` 入口,uvicorn 启动,默认绑 `127.0.0.1:0` 让系统分配端口)
- **手动测试步骤**:
  1. `uv run python -m rosetta.server`(前台跑,记下 stdout 打印的端口号,下文用 `<port>` 代指)
  2. 另开终端:`curl http://127.0.0.1:<port>/admin/ping`
  3. `curl http://127.0.0.1:<port>/admin/status`
  4. 回到 server 终端按 `Ctrl+C` 停掉
- **预期结果**:
  - 步骤 1:stdout 打印形如 `INFO: Uvicorn running on http://127.0.0.1:62538`,无报错
  - 步骤 2:返回 `{"ok":true}`,HTTP 200
  - 步骤 3:返回 JSON,包含 `version` / `uptime_ms` / `providers_count`(即便 DB 未初始化,占位值也行)
  - 步骤 4:server 干净退出,无异常栈
- **通过判据**:两个 admin 端点均返回 200,server 能正常启停
- **风险**:端口 0 拿到的实际端口必须能打印到 stdout(为下一步写 endpoint.json 铺垫)

### 步骤 1.2 · SQLite + providers CRUD(最小集)

- **目标**:DB 落地 + 能增/查 provider(delete / update 留后面)
- **产出**:
  - `rosetta/server/database/models.py`(SQLAlchemy 声明:`providers` / `routes` / `logs` 三张表)
  - `rosetta/server/database/session.py`(aiosqlite engine + async session factory)
  - `rosetta/server/database/migrations/001_init.sql`(DDL 镜像,含 `PRAGMA user_version = 1` 和 `logs.created_at` 索引)
  - `rosetta/server/admin/providers.py`:`GET /admin/providers`、`POST /admin/providers`
  - DB 文件默认位置 `~/.rosetta/rosetta.db`
- **手动测试步骤**:
  1. 起 server(同步骤 1.1),记下 `<port>`
  2. `curl -X POST http://127.0.0.1:<port>/admin/providers -H 'content-type: application/json' -d '{"name":"test-provider","type":"anthropic","api_key":"sk-fake-testing"}'`
  3. `curl http://127.0.0.1:<port>/admin/providers`
  4. `Ctrl+C` 停 server,然后再起一次
  5. `curl http://127.0.0.1:<newport>/admin/providers`
  6. `sqlite3 ~/.rosetta/rosetta.db "PRAGMA user_version;"`
  7. `sqlite3 ~/.rosetta/rosetta.db ".indexes logs"`
- **预期结果**:
  - 步骤 2:HTTP 200,响应 body 含新 provider 的 `id` 和 `created_at`
  - 步骤 3:返回 JSON 数组,含刚建的 `test-provider`
  - 步骤 5:重启后仍能看到 `test-provider`(持久化)
  - 步骤 6:输出 `1`
  - 步骤 7:输出含 `idx_logs_created_at`
- **通过判据**:步骤 5/6/7 全部符合
- **风险**:aiosqlite 的 WAL 模式 / busy_timeout — 建表时统一配置

### 步骤 1.3 · 三格式入口(同格式直通,无翻译)

- **目标**:三条 `/v1/*` 路由,原样 httpx 透传到上游
- **产出**:
  - `rosetta/server/dataplane/routes.py`:`POST /v1/messages` / `POST /v1/chat/completions` / `POST /v1/responses`(v0.1 只做 messages + completions,responses 先返 501)
  - `rosetta/server/dataplane/forwarder.py`:httpx AsyncClient + SSE 透传(`httpx.stream` + `StreamingResponse`)
  - provider 选择**先硬编**:取"第一个 enabled provider"兜底(阶段 3 才引入路由表)
  - `rosetta/shared/formats.py`:三格式枚举 + URL 路径映射 + 内置默认模型表
  - `tests/smoke/smoke_messages.py` + `tests/smoke/smoke_chat.py`(简单脚本)
- **手动测试步骤**:
  1. 准备一个**真实 Anthropic key**,通过 `POST /admin/providers` 建一个 `type=anthropic` 的 provider
  2. 起 server,记 `<port>`
  3. 跑 smoke 脚本,内容大致:
     ```python
     from anthropic import Anthropic
     c = Anthropic(base_url=f"http://127.0.0.1:{PORT}", api_key="dummy")
     with c.messages.stream(model="claude-haiku-4-5", max_tokens=64,
                            messages=[{"role":"user","content":"say hi in 3 words"}]) as s:
         for text in s.text_stream: print(text, end="", flush=True)
     ```
  4. 若有 OpenAI key,同样流程建 `type=openai` provider 然后换 openai SDK 跑 `/v1/chat/completions`
  5. `curl http://127.0.0.1:<port>/v1/responses -d '{}'`
- **预期结果**:
  - 步骤 3:终端逐字输出一句 3-词问候,无异常栈
  - 步骤 4(可选):OpenAI SDK 收到 `ChatCompletionChunk` 流,`delta.content` 逐 token
  - 步骤 5:HTTP 501,body 含"responses endpoint not implemented yet"
- **通过判据**:步骤 3 跑通(messages 直通);OpenAI 条件有的话步骤 4 也跑通
- **风险**:SSE 透传要关 httpx buffer;`StreamingResponse` 的 `media_type` 必须设 `text/event-stream`

### 步骤 1.4 · endpoint.json + spawn.lock + parent-watcher

- **目标**:server 启动写发现文件,支持 CLI/GUI 发现;并发 spawn 安全
- **产出**:
  - `rosetta/server/runtime/endpoint.py`(写 endpoint.json,`.tmp` → `rename` 原子替换)
  - `rosetta/server/runtime/lockfile.py`(`O_CREAT|O_EXCL` 抢 `spawn.lock`,PID 陈旧检测)
  - `rosetta/server/runtime/watcher.py`(`watch_parent` + `graceful_shutdown` 5 步流程)
  - `__main__.py` 接 `--parent-pid` 参数
- **手动测试步骤**:
  1. **场景 A(单进程生命周期)**:
     a. `uv run python -m rosetta.server --parent-pid $$`(`$$` 是当前 shell PID)
     b. 另开终端:`cat ~/.rosetta/endpoint.json`
     c. `ls -la ~/.rosetta/`(看 spawn.lock 状态)
     d. 回到 server 终端 `Ctrl+C`
     e. `ls ~/.rosetta/endpoint.json`(应不存在了)
  2. **场景 B(并发抢锁)**:
     a. `uv run python -m rosetta.server & sleep 0.1; uv run python -m rosetta.server`
     b. 观察两个 server 输出
  3. **场景 C(父进程死 → watcher 触发)**:
     a. 新 shell:`(uv run python -m rosetta.server --parent-pid $$ &)`
     b. `echo $?`,然后关掉这个外层 shell
     c. 等 5 秒,`ls ~/.rosetta/endpoint.json`
- **预期结果**:
  - 场景 A.b:JSON 含 `url` / `token` / `pid` 三字段,url 是 `http://127.0.0.1:<port>`
  - 场景 A.c:`spawn.lock` 已释放(server 正常启动后就该删)
  - 场景 A.d:server 日志出现 `graceful_shutdown` 5 步输出(停 accept → 等请求 → flush logs → 删 endpoint.json → 退出)
  - 场景 A.e:文件不存在
  - 场景 B:只有一个 server 监听端口;另一个打印"server already running at <url>"后 exit 0
  - 场景 C.c:文件不存在(watcher 5s 内触发了 graceful_shutdown)
- **通过判据**:三场景全部符合
- **风险**:Windows 没有 POSIX `O_EXCL` 同义 → 用 `msvcrt.locking` 或 `portalocker`;跨平台抽象放 `lockfile.py`

**=== 阶段 1 整体验收 ===**:三格式原生 SDK 调本地代理,响应与直连一致(messages + completions 对角线必须通,responses 留 501)。

---

## 阶段 2 · 翻译层 v0.1(3-5 天)

### 步骤 2.1 · IR 定义 + Claude adapter(入/出)

- **目标**:定义 Request / Response / Stream Event IR;Claude 格式双向 adapter
- **产出**:
  - `rosetta/server/translation/ir.py`(Pydantic 模型)
  - `rosetta/server/translation/messages/request.py`:`messages_to_ir` + `ir_to_messages`
  - `rosetta/server/translation/messages/response.py`:非流 + 流(`content_block_*` 事件状态机)
  - `tests/translation/fixtures/messages/*.json`(金标样本:简单文本 / 带 system / 带 tool_use / 流式)
  - `tests/translation/test_messages_roundtrip.py`
- **手动测试步骤**:
  1. 准备 fixture:用 anthropic SDK 真调一次 Claude,把 request body 和完整 response(含 SSE 事件序列)存为 JSON
  2. `uv run pytest tests/translation/test_messages_roundtrip.py -v`
- **预期结果**:
  - 步骤 2:每个 fixture 一个 test case,全部 PASSED;逻辑是 `json → messages_to_ir → ir_to_messages → 字段级等价`(排除 id/timestamp 等易变字段)
- **通过判据**:pytest exit 0,所有 fixture 测试绿
- **风险**:`tool_use` block 与 `tool_result` block 的跨消息对应;`content[]` 里文本和工具块混排

### 步骤 2.2 · OpenAI Chat Completions adapter(入/出)

- **目标**:Chat Completions 双向 adapter
- **产出**:
  - `rosetta/server/translation/completions/request.py` + `response.py`
  - `tests/translation/fixtures/completions/*.json`
  - `tests/translation/test_completions_roundtrip.py`
- **手动测试步骤**:
  1. 同 2.1 的 fixture 准备方式,换 openai SDK
  2. `uv run pytest tests/translation/test_completions_roundtrip.py -v`
- **预期结果**:步骤 2 所有 fixture 测试绿
- **通过判据**:pytest exit 0
- **风险**:`message.tool_calls.function.arguments`(字符串)vs Claude `tool_use.input`(object)的字段对齐;`finish_reason` 枚举映射

### 步骤 2.3 · 跨格式翻译(非流式)

- **目标**:Claude ↔ Chat Completions 双向非流式能走通
- **产出**:
  - `rosetta/server/translation/dispatcher.py`(入口 format × 出口 format → 选路径)
  - `rosetta/server/dataplane/routes.py` 接入 dispatcher(替换原透传)
  - `tests/smoke/smoke_crossformat_nonstream.py`
- **手动测试步骤**:
  1. 前提:DB 里有一个 `type=anthropic` 且带真 key 的 provider,**并且它是第一个 enabled**(阶段 3 之前靠兜底)
  2. 起 server
  3. 跑脚本:用 openai SDK 指向本地 `/v1/chat/completions`,`model="claude-haiku-4-5"`,`stream=False`
     ```python
     from openai import OpenAI
     c = OpenAI(base_url=f"http://127.0.0.1:{PORT}/v1", api_key="dummy")
     r = c.chat.completions.create(model="claude-haiku-4-5",
         messages=[{"role":"user","content":"1+1=?"}])
     print(r.choices[0].message.content)
     ```
  4. 看 server 日志里的翻译路径
- **预期结果**:
  - 步骤 3:打印形如 `2`(或自然语言的"等于 2"),不是 JSON 错误
  - 步骤 4:server log 出现 `chat_completions → IR → messages` 的路径标记
- **通过判据**:OpenAI SDK 能解析响应,内容合理;日志显示走了翻译而非直通
- **风险**:翻译失败时要返回 500 + `rosetta_error` body,不要抛栈

### 步骤 2.4 · 跨格式翻译(流式)

- **目标**:流式事件翻译,逐事件 yield 不聚合
- **产出**:
  - `rosetta/server/translation/stream.py`(Stream Event IR + 两侧状态机)
  - 流式错误传播规则(见 `DESIGN.md` §8.3 补丁)
  - `tests/smoke/smoke_crossformat_stream.py`
- **手动测试步骤**:
  1. 前提同 2.3
  2. 用 openai SDK **流式**:同 2.3 但 `stream=True`,逐 chunk 打印 `delta.content`
  3. 反向:用 anthropic SDK 指向本地 `/v1/messages`,`model` 传 OpenAI 模型(需要先把 provider 换成 `type=openai`)
  4. 工具调用:请求带 `tools=[{...简单计算器...}]`,提问让模型必然调工具
  5. 错误传播模拟:临时把 provider 的 api_key 改成错的,重发请求
- **预期结果**:
  - 步骤 2:终端逐 token 出字,不是一次性全吐
  - 步骤 3:收到 `content_block_delta` 事件流
  - 步骤 4:最终 chunk 里 `tool_calls[0].function.arguments` 是完整 JSON 字符串(拼接后)
  - 步骤 5:客户端 SDK 抛的错是对应格式的错误(OpenAI SDK 抛 `APIStatusError`,或流中出现 error event),非 Python 异常泄漏
- **通过判据**:双向流式都通;工具 arguments 拼接正确;错误传播形态合规
- **风险**:Chat Completions 的 `delta.tool_calls[].function.arguments` 和 Claude 的 `partial_json` 分片粒度不同 — adapter 内部要缓冲到完整 JSON 再往另一侧吐

**=== 阶段 2 整体验收 ===**:Claude SDK 调 OpenAI 模型、OpenAI SDK 调 Claude 模型,流式 / 非流式 / 工具调用均正确。

---

## 阶段 2.5 · Responses API(2-3 天)

### 步骤 2.5.1 · Responses adapter(入/出)

- **目标**:Responses API 双向 adapter + 三格式两两互通
- **产出**:
  - `rosetta/server/translation/responses/request.py` + `response.py`
  - `tests/translation/fixtures/responses/*.json`
  - `tests/translation/test_responses_roundtrip.py`
  - dispatcher 加第三条路径
- **手动测试步骤**:
  1. `uv run pytest tests/translation/test_responses_roundtrip.py -v`(roundtrip)
  2. 跑 smoke 脚本:用 openai SDK 的 `responses.create` 指向本地,model 传 Claude 的
  3. 反向:用 anthropic SDK 指向本地,provider 是 `type=openai` 但 URL 是 responses 端点
- **预期结果**:
  - 步骤 1:pytest 全绿
  - 步骤 2:Responses SDK 收到有效 `Response` 对象,`.output[0]` 是 Claude 的文本
  - 步骤 3:Claude SDK 收到 `content_block_delta` 流
- **通过判据**:6 条跨格式路径全部跑通
- **风险**:Responses 事件种类最多,流式状态机最复杂

### 步骤 2.5.2 · 有状态特性降级

- **目标**:`store` / `previous_response_id` / `background` / 内置 tools 的降级策略
- **产出**:
  - dispatcher 按 `DESIGN.md` §8.3 表格处理降级
  - `x-rosetta-warnings` 响应头拼装
  - `tests/translation/test_responses_degradation.py`
- **手动测试步骤**:
  1. `uv run pytest tests/translation/test_responses_degradation.py -v`
  2. 手测:用 openai SDK `responses.create(..., previous_response_id="resp_xxx")`,provider 是 type=anthropic(即要翻到 Claude)
  3. 手测:用 openai SDK `responses.create(..., store=True)`,provider 是 type=anthropic
  4. 手测:用 openai SDK `responses.create(..., tools=[{"type":"web_search"}])`,provider 是 type=anthropic
- **预期结果**:
  - 步骤 1:全绿
  - 步骤 2:返回 HTTP 400,body 的 `error.code = "stateful_not_translatable"`
  - 步骤 3:返回 200,响应头含 `x-rosetta-warnings: store_ignored`,正文正常
  - 步骤 4:返回 200,响应头含 `x-rosetta-warnings: builtin_tools_removed:web_search`
- **通过判据**:四条降级场景全部符合
- **风险**:warnings 头格式定清楚(推荐 CSV,例:`a,b=v,c=v1;v2`)

**=== 阶段 2.5 整体验收 ===**:3 条对角线直通 + 6 条跨格式翻译共 9 条路径全部可走。

---

## 阶段 3 · 路由规则 + loopback(1 天)

### 步骤 3.1 · routes 表 + 匹配逻辑 + `x-rosetta-provider`

- **目标**:实现 §8.4 的 7 条匹配规则;支持 header 绕路由;异格式自动翻译
- **产出**:
  - `rosetta/server/admin/routes.py`(`GET /admin/routes` / `PUT /admin/routes`)
  - `rosetta/server/dataplane/router.py`(匹配逻辑)
  - 异格式回退自动走翻译的接线(`DESIGN.md` §8.4 补丁)
- **手动测试步骤**:
  1. 建 2 个 provider:`test-ant`(type=anthropic,真 key)+ `test-oai`(type=openai,真 key)
  2. `curl -X PUT http://127.0.0.1:<port>/admin/routes -H 'content-type: application/json' -d '[{"model_glob":"claude-*","provider":"test-ant","priority":1},{"model_glob":"gpt-*","provider":"test-oai","priority":2}]'`
  3. `curl http://127.0.0.1:<port>/admin/routes`
  4. 打 claude 模型:一次 `POST /v1/messages` `model=claude-haiku-4-5`
  5. 打 gpt 模型:一次 `POST /v1/chat/completions` `model=gpt-4o-mini`
  6. 打不匹配的:一次 `POST /v1/messages` `model=foo-bar`(走兜底)
  7. 打 gpt 模型但带 header `x-rosetta-provider: test-ant`
  8. `sqlite3 ~/.rosetta/rosetta.db "SELECT id, provider_id, model FROM logs ORDER BY id DESC LIMIT 4;"`
  9. `sqlite3 ~/.rosetta/rosetta.db "SELECT id, name FROM providers;"`(对照 provider_id)
- **预期结果**:
  - 步骤 3:返回刚才 PUT 的 2 条规则
  - 步骤 4-7:都返回正常响应
  - 步骤 8-9 交叉:最近 4 条日志的 provider 名对应 `test-ant / test-oai / test-ant(第一个 enabled 兜底) / test-ant(header 绕路由)`
- **通过判据**:4 条路径都按预期路由
- **风险**:glob 匹配用 `fnmatch` 够;优先级相同时用 id 做稳定排序

### 步骤 3.2 · loopback 绑定 + 数据面 api-key 透传

- **目标**:server 只接 loopback;`x-api-key` / `Authorization` 透传规则
- **产出**:
  - `__main__.py` 绑定 `127.0.0.1` + `::1`(双栈),拒绝其他来源
  - `forwarder.py` 里:客户端带 key → 透传(按上游 type 选 header 名);不带 → `providers.api_key` fallback
  - 临时在 forwarder 加一行 debug log 打印"发给上游的 Authorization 的前 10 字符"(验证完删)
- **手动测试步骤**:
  1. 起 server,看日志绑定信息,确认是 `127.0.0.1` / `[::1]` 而非 `0.0.0.0`
  2. 从同局域网另一台机器 curl 本机内网 IP:<port>/admin/ping
  3. 不带 key 发一条请求:`curl POST /v1/messages -d '{"model":"claude-haiku-4-5",...}'`(不加 `x-api-key` 头)
  4. 带 override:同请求加 `-H 'x-api-key: sk-ant-OVERRIDE-TEST'`(注意这个 key 要在 Anthropic 无效,用来触发可观察的上游错误)
  5. 看 server 的 debug log 里发给上游的 key 前缀
- **预期结果**:
  - 步骤 1:日志形如 `Uvicorn running on http://127.0.0.1:62538` 和 `[::1]:62538`
  - 步骤 2:TCP 连不上 / timeout
  - 步骤 3:上游正常响应(用了 DB 里的 key);debug log 显示发给上游的 key 前缀 = DB 里存的 key 前缀
  - 步骤 4:上游报 `invalid_api_key`;debug log 显示发给上游的 key 前缀 = `sk-ant-OVE...`
- **通过判据**:loopback 绑定生效;两种 key 路径都能从 log 里看到正确值
- **风险**:IPv6 localhost 拼 URL 是 `[::1]:port`;忘删 debug log 会泄露 key 前缀到日志

**=== 阶段 3 整体验收 ===**:多 provider 按模型名自动路由;api-key 覆盖与兜底都正确。

---

## 阶段 4 · SDK + CLI + chat 命令(1-1.5 天)

### 步骤 4.1 · `rosetta.sdk`:discover + ProxyClient

- **目标**:SDK 能发现/启动 server + 封装 /admin 调用
- **产出**:
  - `rosetta/sdk/discover.py`:读 `endpoint.json` → 不存在/死了 → spawn → 轮询 `/admin/ping`
  - `rosetta/sdk/client.py`:`ProxyClient.discover()` / `.direct(base_url, api_key, format, model)` 两种工厂
  - `rosetta/sdk/chat.py`:`chat_once(text, model, format)` → `ChatResult(text, usage, path, latency_ms)`
  - `tests/sdk/test_discover.py`
- **手动测试步骤**:
  1. 确保没有 server 在跑:`rm -f ~/.rosetta/endpoint.json`,`pkill -f rosetta.server`(Windows:`taskkill /F /IM python.exe` 慎用)
  2. 跑 `uv run pytest tests/sdk/test_discover.py -v -s`
  3. 测试里要包含"server 未跑 → SDK spawn"场景:断言 `ChatResult.text` 非空,且 `~/.rosetta/endpoint.json` 出现
  4. 不关测试中起的 server,再跑一次:`uv run python -c "import asyncio; from rosetta.sdk import ProxyClient; asyncio.run(...)"` 做 discover 调用
- **预期结果**:
  - 步骤 2:测试绿
  - 步骤 3 中:`tasklist` / `ps` 能看到新的 python 子进程
  - 步骤 4:复用已有 server(endpoint.json 的 pid 不变),不新起进程
- **通过判据**:spawn 和复用两场景均测试通过
- **风险**:spawn 的 subprocess 必须 detach(server 进程独立于 SDK caller 生命周期)

### 步骤 4.2 · CLI 管理命令

- **目标**:`rosetta status / start / stop / provider / route / logs / stats`
- **产出**:
  - `rosetta/cli/__main__.py`(typer 根)
  - `rosetta/cli/commands/{status,start,stop,provider,route,logs,stats}.py`
- **手动测试步骤**:
  1. `uv run rosetta provider add --name ant-main --type anthropic --api-key sk-ant-XXX`
  2. `uv run rosetta provider list`
  3. `uv run rosetta route add --pattern 'claude-*' --provider ant-main`
  4. `uv run rosetta route list`
  5. `uv run rosetta status`
  6. `uv run rosetta logs -n 10`
  7. `uv run rosetta stats`
  8. `uv run rosetta stop`
  9. `uv run rosetta status`(stop 之后)
- **预期结果**:
  - 步骤 1:打印新 provider 摘要(name / type / id / enabled=true)
  - 步骤 2:表格含刚建的 provider
  - 步骤 3:打印新 route 摘要
  - 步骤 4:表格含 pattern / provider / priority
  - 步骤 5:显示 server 状态(`running · pid=xxx · port=xxx`)+ providers 数 + routes 数
  - 步骤 6:按时间降序显示最近 10 条(可能为空,显示 "no logs yet")
  - 步骤 7:显示今日总请求数 / 成功率 / 平均延迟
  - 步骤 8:提示"server stopped"
  - 步骤 9:显示 `not running`
- **通过判据**:9 条命令均 exit 0,输出合理
- **风险**:`rosetta start` / `stop` 生命周期语义要和 sidecar 模型对齐(stop 是发 shutdown 信号给 server,不是杀进程)

### 步骤 4.3 · `rosetta chat`:一次性 + REPL

- **目标**:两种模式 + `/exit /reset /model /format` 命令
- **产出**:
  - `rosetta/cli/commands/chat.py`
  - `rosetta/cli/repl.py`
  - `rosetta/cli/render.py`(流式 token 打印、meta 行、错误气泡)
- **手动测试步骤**:
  1. 一次性:`uv run rosetta chat "1+1=?"`
  2. REPL 进入:`uv run rosetta chat`
  3. REPL 里连续 3 轮:"介绍下自己" → "再详细点" → "用中文重说",然后 `/exit`
  4. REPL 里切模型和格式:`/model claude-sonnet-4-5` → 发一句 → `/format completions` → 发一句 → `/reset` → 发一句
  5. 跨格式:`uv run rosetta chat --format completions --model gpt-4o-mini "ping"`
  6. 指定 provider:`uv run rosetta chat --provider ant-main "hi"`
- **预期结果**:
  - 步骤 1:流式逐 token 打印回复,末尾 meta 行形如 `[ant-main · claude-haiku-4-5 · 8→21 tok · 412ms · messages↔messages]`
  - 步骤 3:第 3 轮用中文回答,连贯前面两轮的内容
  - 步骤 4:切 model/format 立即生效下一轮;`/reset` 后消息数组清空
  - 步骤 5:meta 行显示 `completions→IR→messages`(跨格式翻译路径)
  - 步骤 6:meta 行 provider 字段显式是 `ant-main`,日志表的 provider_id 对应
- **通过判据**:6 个场景全部符合
- **风险**:Windows terminal 的 ANSI 颜色;typer 对多词 positional 的处理

### 步骤 4.4 · direct 模式 + 互斥校验

- **目标**:`--base-url` 触发 direct;与 `--provider` 互斥
- **产出**:
  - `rosetta/cli/commands/chat.py` 参数解析分支
  - direct 模式走 `ProxyClient.direct()`,绕 server
- **手动测试步骤**:
  1. 记下当前 `~/.rosetta/endpoint.json` mtime 和 logs 表最大 id
  2. `uv run rosetta chat --base-url https://api.anthropic.com --api-key sk-ant-XXX --format messages --model claude-haiku-4-5 "hi"`
  3. 再检 endpoint.json mtime(应不变)和 logs 最大 id(应不变)
  4. `uv run rosetta chat --base-url https://api.anthropic.com --provider foo "hi"`
  5. `uv run rosetta chat --base-url https://api.openai.com --api-key sk-XXX --format messages --model gpt-4o-mini "hi"`(format 不匹配上游方言)
- **预期结果**:
  - 步骤 2:返回 Claude 回复,meta 行前缀是 `[direct · api.anthropic.com · ...]`
  - 步骤 3:endpoint.json mtime 未变,logs 表无新增
  - 步骤 4:stderr 提示"--base-url 与 --provider 互斥",exit 2
  - 步骤 5:stderr 提示"format 和上游方言不一致",exit 2(若无法检测则至少上游返回 4xx 时 CLI 报错清晰)
- **通过判据**:direct 真未经 server;两个互斥校验正确拦截
- **风险**:direct 时如果 server 恰好在跑,要确保代码路径**真的**没向 localhost 发请求(关键看日志)

**=== 阶段 4 整体验收 ===**:按 `DESIGN.md` §10 "CLI 完整使用 demo" 跑 step 1~8 全通。

---

## 阶段 5 · 前端(3-4 天)

### 步骤 5.1 · Vite + React + Tailwind + shadcn 脚手架

- **目标**:前端工程跑起来
- **产出**:
  - `packages/app/`(bun workspace)
  - Vite + TS + Tailwind + shadcn/ui 初始化
  - `src/api/`(/admin/* 的 OpenAPI 自动生成 client)
  - `src/routes.tsx`:Dashboard / Providers / Logs / Chat 四页
- **手动测试步骤**:
  1. `cd packages/app && bun install`
  2. `bun run dev`
  3. 打开浏览器 `http://localhost:5173`(或 vite 提示的端口)
  4. 点左侧导航切 Dashboard / Providers / Logs / Chat 四页
  5. 打开浏览器 DevTools Console
- **预期结果**:
  - 步骤 2:vite 启动成功,无 bundling 错误
  - 步骤 3:页面打开,能看到 4 个导航项
  - 步骤 4:切页不报错,每页至少有 placeholder 文案或空状态
  - 步骤 5:Console 无红色 error(warning 可以)
- **通过判据**:4 页都能切,console 无 error
- **风险**:shadcn 要配 `components.json`;Tailwind 路径别名

### 步骤 5.2 · Dashboard + Providers

- **目标**:能看 server 状态 + 增删 provider
- **产出**:`src/pages/Dashboard.tsx` + `src/pages/Providers.tsx`
- **手动测试步骤**:
  1. 前提:server 跑着,DB 里有 1 个 provider
  2. Dashboard 页:看是否显示 `running · provider count: 1`
  3. Providers 页:看列表含现有 provider
  4. 点"Add provider":填表(name / type / api_key),提交
  5. 刷新页面(F5),看新 provider 是否还在
  6. 点某 provider 的删除按钮,确认对话框后删除
  7. `sqlite3 ~/.rosetta/rosetta.db "SELECT id, name FROM providers ORDER BY id;"` 核对
- **预期结果**:
  - 步骤 2:Dashboard 显示正确状态
  - 步骤 5:新建的 provider 仍在列表
  - 步骤 6:列表里消失
  - 步骤 7:DB 状态与 UI 一致
- **通过判据**:增删后 DB 和 UI 同步
- **风险**:删除做乐观更新要加确认

### 步骤 5.3 · Chat 页(核心)

- **目标**:多轮对话 + 流式 + 三下拉联动
- **产出**:`src/pages/Chat.tsx` + SSE fetch 逻辑 + React state 存 messages
- **手动测试步骤**:
  1. Chat 页默认 `format=messages`,`provider=<自动路由>`,`model=claude-haiku-4-5`
  2. 输入 "你好" → Send
  3. 发第二轮 "再详细点"
  4. 切 `format` 到 `completions`:观察 model 下拉重新加载;选个 gpt 模型 → 发一条
  5. 开始一条长回复,中途点 Stop
  6. 点右上 "Override api-key":填入某个 key → 发一条 → 打开 DevTools Network 看请求 header
  7. 清 Override,再发一条,看 header 是否不带 `x-api-key`
  8. 点 "New chat" → 历史清空,重新开始
- **预期结果**:
  - 步骤 2:token 增量渲染,完成后显示 meta 行
  - 步骤 3:回复能连贯前文
  - 步骤 4:Model 下拉刷新为 OpenAI 模型列表,发送请求的 URL 是 `/v1/chat/completions`
  - 步骤 5:流停止,UI 显示 "已中断";不影响下一轮
  - 步骤 6:Network 里该请求有 `x-api-key: <填入的>`
  - 步骤 7:Network 里该请求**无** `x-api-key` 头
  - 步骤 8:消息列表清空
- **通过判据**:8 项全通
- **风险**:切 format 后 tool_use / thinking 块要 toast 提示被丢弃

### 步骤 5.4 · Logs 页

- **目标**:日志列表 + 分页 + provider / 时间筛选
- **产出**:`src/pages/Logs.tsx`
- **手动测试步骤**:
  1. 前提:DB 里有 30+ 条 log(可从前面步骤积累)
  2. 打开 Logs 页,看默认视图
  3. 点"下一页"
  4. 选某 provider 筛选
  5. 选时间段(如"今天")
  6. 清筛选
- **预期结果**:
  - 步骤 2:按时间降序显示最近 20(或默认 page size)条
  - 步骤 3:翻到下一批
  - 步骤 4:列表只剩该 provider 的条目
  - 步骤 5:列表只剩时间段内的条目
  - 步骤 6:回到默认视图
- **通过判据**:分页 + 两种筛选 + 清空都正确

**=== 阶段 5 整体验收 ===**:浏览器里直连本地 server,四页全功能可用。

---

## 阶段 6 · 打包(1 天)

### 步骤 6.1 · PyInstaller 单 exe

- **目标**:server 和 CLI 各打一个单文件 exe
- **产出**:
  - `scripts/build.py`
  - `build/rosetta.spec` + `build/rosetta-server.spec`
- **手动测试步骤**:
  1. `uv run python scripts/build.py`
  2. `ls -la dist/`
  3. 另开终端(注意:**不要在 uv run 里**),直接:`./dist/rosetta-server.exe`
  4. `curl http://127.0.0.1:<port>/admin/ping`
  5. `./dist/rosetta.exe status`
  6. `./dist/rosetta.exe chat "hi"`(前提:DB 里有 provider)
- **预期结果**:
  - 步骤 2:两个 exe 文件,各约 30-80 MB
  - 步骤 3:exe 独立能起 server,无"找不到模块"报错
  - 步骤 4:`{"ok":true}`
  - 步骤 5:显示 `running · ...`
  - 步骤 6:正常聊天
- **通过判据**:无 uv/venv 环境下 exe 独立运行全链路成功
- **风险**:httpx / aiosqlite 的 hidden imports 要在 spec 里声明;SSL 证书打包路径

### 步骤 6.2 · CI 产 artifact

- **目标**:打 tag 时 CI 自动产 exe 并 attach 到 Release
- **产出**:`.github/workflows/release.yml`
- **手动测试步骤**:
  1. `git tag v0.0.1-test && git push origin v0.0.1-test`
  2. 去 GitHub Actions 页面看 release workflow 触发
  3. 等跑完(5-15 分钟),去 Releases 页
  4. 下载 release asset
  5. 本地双击运行验证
  6. 收尾:`git tag -d v0.0.1-test && git push --delete origin v0.0.1-test`;GitHub Releases 页手动删该 Release
- **预期结果**:
  - 步骤 2:看到 release job 跑
  - 步骤 3:Releases 页有 `v0.0.1-test` 发布,附件含 exe
  - 步骤 5:exe 能跑
- **通过判据**:从 tag 到可下载 exe 全链路打通

---

## 阶段 7 · Tauri 外壳(2-3 天)

### 步骤 7.1 · Tauri 工程 + sidecar 启动

- **目标**:桌面 app 启动时拉起 `rosetta-server.exe` 作为 sidecar
- **产出**:`packages/desktop/`(Tauri 2.x) + `tauri.conf.json` 的 sidecar 配置
- **手动测试步骤**:
  1. `cd packages/desktop && bun install`
  2. `bun run tauri dev`
  3. 窗口弹出后,打开 Windows 任务管理器(或 `tasklist | findstr rosetta-server`)
  4. 前端的 Providers / Chat 页做简单操作
- **预期结果**:
  - 步骤 2:窗口弹出,前端加载成功
  - 步骤 3:看到一个 `rosetta-server.exe` 子进程
  - 步骤 4:API 调用正常,能增删 provider、能发一条 chat
- **通过判据**:桌面端与 sidecar 通信正常

### 步骤 7.2 · 窗口记忆 + 托盘 + 关窗优雅退出

- **目标**:用户体验完善
- **产出**:`tauri-plugin-window-state` + tray icon + `on_close` 调 `/admin/shutdown`
- **手动测试步骤**:
  1. 打开 app,挪动窗口到右下角,改小窗口
  2. 关窗 → 重开 app → 看位置/大小是否保持
  3. 点"最小化到托盘"→ 任务栏消失,托盘出现图标
  4. 点托盘图标 → 窗口恢复
  5. 从托盘右键 → `Exit`
  6. 立即 `tasklist | findstr rosetta-server`
  7. 5 秒后再看
  8. `ls ~/.rosetta/endpoint.json`
- **预期结果**:
  - 步骤 2:位置和大小保持
  - 步骤 4:窗口恢复到原位
  - 步骤 6:server 进程**还在**(这时 graceful_shutdown 正在跑)
  - 步骤 7:server 进程消失
  - 步骤 8:文件不存在
- **通过判据**:窗口记忆生效,托盘正常,关闭后 server 在 ~5s 内退出

**=== 阶段 7 整体验收 ===**:`tauri dev` 桌面端与浏览器内表现一致。

---

## 阶段 8 · 打磨与发布(1-2 天)

### 步骤 8.1 · 错误态 UI + 空状态

- **目标**:providers 空时引导 / server 挂了重连 / 流式中断 retry / Logs 空列表
- **手动测试步骤**:
  1. 清空 providers(`DELETE FROM providers;`),打开 app → Providers 页
  2. 打开 app,发送 chat,然后手动 kill server 进程,再发一条
  3. 发一条长 chat,流式中途断网(飞行模式或拔线)
  4. 清空 logs 表,打开 Logs 页
- **预期结果**:
  - 步骤 1:Providers 页显示"暂无 provider,点这里添加"的引导卡,非白屏
  - 步骤 2:UI 显示"连接 server 失败,点击重试"
  - 步骤 3:消息尾部出现"已断开"+ "重试"按钮
  - 步骤 4:Logs 页显示"尚无请求日志"的空状态
- **通过判据**:4 个场景都有合理兜底

### 步骤 8.2 · 自动更新

- **目标**:`tauri-plugin-updater` 接入
- **手动测试步骤**:
  1. 本地搭 mock updater server(tauri-plugin-updater 文档有示例)
  2. `updater.json` 指向 v0.1.0 的假"新版本"
  3. app 里手动触发 check update(或启动自动 check)
  4. 看"发现新版本"提示
  5. 点"升级"
  6. 等待下载 + 重启
  7. 看版本号是否更新
- **预期结果**:
  - 步骤 4:弹窗提示
  - 步骤 7:app 启动后版本号更新到 0.1.0
- **通过判据**:整个升级链路走通

### 步骤 8.3 · 代码签名 + 安装包 + 首个 Release

- **目标**:`Rosetta-Setup-v0.1.0.exe`
- **手动测试步骤**:
  1. 本地跑 `bun run tauri build`,用签名证书打包
  2. 找一台干净的 Windows 机器(或虚拟机)
  3. 双击 `Rosetta-Setup-v0.1.0.exe` 安装
  4. 启动安装后的 Rosetta
  5. 跑一次 chat
  6. 控制面板卸载
  7. 检查残留:`ls ~/.rosetta/`;注册表搜 `Rosetta`
- **预期结果**:
  - 步骤 3:无 Windows SmartScreen 警告(前提:签了有效证书)
  - 步骤 5:开箱即用
  - 步骤 6:应用从开始菜单和 Program Files 移除
  - 步骤 7:`~/.rosetta/` 里用户数据保留(正确行为);注册表项被清理
- **通过判据**:装 → 用 → 卸全链路干净,无警告 / 无残留

---

## 预估与节奏

- 阶段 0-4(核心后端 + CLI):6-10 人日
- 阶段 5(前端):3-4 人日
- 阶段 6-8(打包/Tauri/发布):4-6 人日
- **总计 13-20 人日**

核心价值集中在阶段 2 / 2.5(翻译层),其他阶段都围绕它服务。

---

## 执行约定(与 `CLAUDE.md` 一致)

- 每完成一步:跑"手动测试步骤" → 对照"预期结果" → 判断是否达到"通过判据" → 在 `PROCESS.md` 追加记录 → 请求确认
- 得到"通过" / "继续" / "go" 才进入下一步
- 如果步骤中途发现任务定义需要改,**停下来在 `PROCESS.md` 记一笔**,再回来修 `FEATURE.md`,不要绕开

---

## 附录 A · 节奏建议

阶段 2 / 2.5(翻译层)是项目核心价值,其他阶段都围绕它服务。写代码时:

1. **先写死一个上游**把阶段 1 跑通,别等三种都齐
2. **翻译层先用 fixture 驱动 TDD** —— 拿 Anthropic 官方 SDK 示例 + OpenAI 官方 SDK 示例作为金标样本
3. **流式测试永远用真实 SDK**,不要手写 SSE 字符串对比 —— SDK 层的解析行为才是真正的"客户端期望"
4. **阶段 6 打包尽早做一次**,不要等所有功能做完才第一次 PyInstaller —— 打包踩坑的修复成本随项目复杂度指数上升

---

## 附录 B · v1+ 后续方向(v0 不做,记着)

### 数据面体验
- **Chat 会话持久化** —— 新增 `conversations` / `messages` 表 + `/admin/conversations/*` 端点 + GUI 侧栏会话列表、历史翻阅、会话导出。v0 Chat 页只在内存保留,v1 升级为真的能翻旧对话。
- **Chat 原始请求/响应预览面板** —— Chat 页可折叠 JSON 面板,显示每轮请求体 + 响应体(含 SSE 完整事件序列)。翻译器 / 状态机 bug 的最快排查工具。
- **CLI Chat 增强** —— 多会话文件(`rosetta chat --session foo`,`~/.rosetta/sessions/*.json`)、会话导入导出、tools 交互(显示 tool_use、允许手填 tool_result 继续)。

### 翻译与协议
- 翻译层健壮性打磨(多模态 / 罕见 `tool_choice` 组合 / 边缘字段回写)
- Responses API 有状态特性完整支持(`previous_response_id` 跨翻译、background jobs)
- 模型别名 / 虚拟模型(把 `gpt-5` 别名到 Anthropic 上游的 `claude-4.5`)

### 管理面体验
- 实时日志流(WebSocket)
- Provider PUT / DELETE + connectivity test
- 路由规则拖拽排序
- 用量统计(按 key / provider / model 切分,时间序列图)

### 运维 / 扩展
- 配置导入导出(`rosetta config export/import`,便于多机同步)
- 请求日志 TTL 清理策略
- 多用户账户(多台机器共享一个 server 实例)
- 多语言(i18n)
- 跨平台打包(macOS / Linux)
