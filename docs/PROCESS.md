# Rosetta 执行进度日志

> **文件定位**:动态执行日志。"做到哪了 / 每步实际发生了什么"。
>
> 配套三文件:
> - [`DESIGN.md`](./DESIGN.md) — 架构真源
> - [`FEATURE.md`](./FEATURE.md) — 任务清单
> - `PROCESS.md` — 执行日志(本文件)
>
> **写入规则**:
> - **append-only**:已完成的步骤条目不回写、不删除;需要更正时追加"勘误"条目
> - 每步完成后由 Claude 追加一条新段;用户确认后在该段补上 `**用户确认**` 字段
> - 偏差、临时决策、超纲工作都在对应段的 `**偏差 / 备注**` 里记
>
> **条目模板**(复制粘贴用):
>
> ```markdown
> ## 步骤 X.Y · <标题>
>
> - **开始**:YYYY-MM-DD HH:MM
> - **完成**:YYYY-MM-DD HH:MM
> - **产出**:
>   - `path/to/file1`
>   - `path/to/file2`
> - **验证命令**:
>   ```bash
>   <command>
>   ```
> - **验证结果**:✅ / ❌ + 简述
> - **用户确认**:YYYY-MM-DD HH:MM · "<原话>"
> - **偏差 / 备注**:<若与 FEATURE.md 的定义有出入,在此说明原因>
> ```

---

## 变更日志(元)

记录 `FEATURE.md` / `DESIGN.md` / 本文件结构的调整,不记步骤执行细节。

- **2026-04-21** · 初始化三文件体系:`DEV_PLAN.md` → `FEATURE.md`;新建 `PROCESS.md`;`DESIGN_multi_pkg.md` / `DESIGN_TS.md` 移入 `archive/`
- **2026-04-21** · 删除 `ROADMAP.md`,其 v1+ 方向和节奏建议并入 `FEATURE.md` 附录 A/B
- **2026-04-21** · `FEATURE.md` 所有 30 步的 `**验证**` 字段改成三段式:`**手动测试步骤**`(编号动作) + `**预期结果**`(逐条对应输出) + `**通过判据**`(一行完成标志);`CLAUDE.md` 对应更新
- **2026-04-21** · DESIGN.md 补入 6 处逻辑漏洞修补(endpoint.json 抢锁、watcher 优雅关闭、流式错误传播、路由异格式回退自动翻译、direct 模式互斥校验、logs 索引 + schema 迁移)
- **2026-04-21** · DESIGN.md 同步实际布局(5 处):(a) §7 `server/` 目录从"横切(api/schemas/services/)"改为"纵切(admin/ + dataplane/ + db/ + translation/ 嵌套)"以对齐阶段 1.1-1.3 实装;(b) §8.2 补 migration 实现约定(SQLAlchemy 事务/目录扫描/版本自检/独立事务);(c) tech stack 措辞精确化(aiosqlite 表述为"底层驱动");(d) ASCII 图中"keys"表引用清除;(e) `POST /admin/providers/{id}/test` 端点标注推迟到 v1+

---

## 步骤执行记录

<!--
  每个步骤完成后 append 一条,按上面的模板。
  最新的步骤在最下面(append-only,按时间顺序)。
-->

## 步骤 0.1 · Python 工程骨架

- **开始**:2026-04-21
- **完成**:2026-04-21
- **产出**:
  - `pyproject.toml`(`rosetta-proxy` distribution,hatchling 构建,`[project.scripts]` 注册 `rosetta` / `rosetta-server`)
  - `.python-version`(钉 `3.12`)
  - `rosetta/__init__.py`(带 `__version__ = "0.1.0"` 和包 docstring)
  - `rosetta/{server,sdk,cli,shared}/__init__.py`(空占位)
  - `uv.lock`(由 `uv sync` 生成)
  - `.venv/`(由 `uv sync` 生成,.gitignore 已排除)
- **手动测试结果**:
  - 步骤 1 `uv sync`:✅ 下载 CPython 3.12.13、创建 `.venv/`、安装 `rosetta-proxy==0.1.0`,无报错
  - 步骤 2 `import rosetta; print(rosetta.__file__)`:✅ 输出 `D:\opendemo\claudedemo\rosetta\rosetta\__init__.py`
  - 步骤 3 `from rosetta import server, sdk, cli, shared; print('ok')`:✅ 输出 `ok`
- **通过判据**:✅ 三条命令 exit 0,输出符合预期
- **用户确认**:2026-04-21 · "提交本步骤代码,并开始下一步"
- **偏差 / 备注**:
  - 前置补记:uv 本机未预装,通过 `python -m pip install uv` 装了 0.11.7(走了用户选的选项 3)。`FEATURE.md` 步骤 0.1 默认 uv 就位,实际新机器需先装 uv。暂不改 FEATURE,后续若换机再考虑补一个"步骤 0.0 · 环境预检"。
  - `uv sync` 警告 `Failed to hardlink files; falling back to full copy`:跨盘 / 跨文件系统的常见提示,不影响功能,可选加 `export UV_LINK_MODE=copy` 消警告。
  - `[project.scripts]` 注册的 `rosetta` / `rosetta-server` 当前指向尚未创建的 `rosetta.cli.__main__:main` 和 `rosetta.server.__main__:main`。`uv sync` 不校验 entry point 存在性,shim 仍生成;直接运行 `rosetta` 会 ImportError,符合预期(这些模块在步骤 1.1 / 4.2 才落地)。

---

## 步骤 0.2 · Lint / 类型 / 测试基建

- **开始**:2026-04-21
- **完成**:2026-04-21
- **产出**:
  - `ruff.toml`(line-length=100;启用 E / F / I / B / UP / N / SIM / RUF 规则族;format 双引号;tests/ 放宽命名规则)
  - `mypy.ini`(strict + warn_unreachable + pretty)
  - `tests/__init__.py`(空)
  - `tests/test_smoke.py`(1 个测试:`rosetta.__version__ == "0.1.0"`)
  - `pyproject.toml` 更新:`[dependency-groups] dev = [ruff, mypy, pytest, pytest-asyncio]`;`[tool.pytest.ini_options]`(testpaths, asyncio_mode=auto)
  - `uv.lock` 更新(新增 dev 依赖)
- **手动测试结果**:
  - 步骤 1 `uv run ruff check .`:✅ `All checks passed!`
  - 步骤 2 `uv run ruff format --check .`:✅ `7 files already formatted`
  - 步骤 3 `uv run mypy rosetta/`:✅ `Success: no issues found in 5 source files`
  - 步骤 4 `uv run pytest`:✅ `1 passed in 0.02s`
- **通过判据**:✅ 四条命令 exit 0
- **用户确认**:2026-04-21 · "通过"
- **偏差 / 备注**:
  - 装出的实际版本:ruff 0.15.11,pytest 9.0.3,pytest-asyncio 1.3.0(uv 自行解析到最新兼容)。pytest 9 相对 FEATURE 写的 `>=8` 更新但行为兼容。
  - mypy 选了 `strict = True` 起步。当前代码规模小,strict 没报任何问题;后续引入 httpx / sqlalchemy 等无官方 stubs 的库时,可能需要加 `[mypy-<module>]` 块 `ignore_missing_imports = true`。

---

## 步骤 0.3 · 基础 CI(GitHub Actions)

- **开始**:2026-04-21
- **完成**:2026-04-21
- **产出**:
  - `.github/workflows/ci.yml`:
    - 触发:push/PR 到 main
    - matrix:windows-latest + ubuntu-latest(`fail-fast: false`)
    - 步骤:`actions/checkout` → `astral-sh/setup-uv@v3`(enable-cache) → `uv sync --frozen` → ruff check → ruff format check → mypy → pytest
    - concurrency:同分支后续 push 取消在途 run
    - permissions:contents: read(最小化)
- **手动测试结果**:
  - 直接推 commit 228fc3f 到 main 触发 CI(跳过 FEATURE 写的"临时分支 ci-test"路径 — 直接推 main 同样触发,更简洁)
  - 通过 GitHub REST API 轮询 `https://api.github.com/repos/cliffordll/rosetta/actions/runs`:
    - run id 24701532639,status=completed,conclusion=success
    - 两个 job 均 ✅:
      - `check (ubuntu-latest)`:12s(02:53:36 → 02:53:48)
      - `check (windows-latest)`:25s(02:53:36 → 02:54:01)
- **通过判据**:✅ 最新 CI run 为 success,两个平台都绿
- **用户确认**:2026-04-21 · "通过"
- **偏差 / 备注**:
  - FEATURE 原设计用临时 `ci-test` 分支触发,实际直接推 main 就触发(yml 配的 `on: push: branches: [main]`)。省了"新建分支 → 推送 → 删分支"的环节。后续改动若想不污染 main 历史,仍可用 PR 流程(yml 也监听 pull_request)。
  - 第一次 run 特别快(12-25s),部分原因是 setup-uv 的 cache 首次就命中(astral-sh/setup-uv 有跨 job 共享的全局缓存)+ 无其他 jobs 排队。后续加依赖后会变慢一些。
  - 本机没装 `gh` CLI,监控用的 curl + GitHub API。对 public 仓库免鉴权就能查 runs/jobs。若以后要本地触发 re-run,可以 `winget install --id=GitHub.cli -e`。

---

## 变更 · 步骤 0.2 / 0.3:类型检查器 mypy → pyright

- **变更时间**:2026-04-21
- **触发**:用户要求替换
- **影响范围**:步骤 0.2(lint/类型/测试基建)和 0.3(CI)的产出
- **改动清单**:
  - `pyproject.toml` 的 dev deps:`mypy>=1.10` → `pyright>=1.1.380`
  - 删除 `mypy.ini`
  - 新建 `pyrightconfig.json`(`include: ["rosetta"]`、`pythonVersion: "3.12"`、`typeCheckingMode: "strict"`、`useLibraryCodeForTypes: true`)
  - `.github/workflows/ci.yml`:步骤 `uv run mypy rosetta/` → `uv run pyright rosetta/`
- **重新验证(本地)**:
  - `uv run ruff check .`:✅
  - `uv run ruff format --check .`:✅
  - `uv run pyright rosetta/`:✅ `0 errors, 0 warnings, 0 informations`
  - `uv run pytest`:✅ `1 passed`
- **重新验证(CI)**:commit `60a0e20` 触发 run 24701741897 → conclusion `success`
  - `check (ubuntu-latest)`:9s ✅
  - `check (windows-latest)`:30s ✅
- **用户确认**:2026-04-21 · "通过"
- **备注**:
  - 实装版本 pyright 1.1.408(2026-04 最新)。pyright 通过 `nodeenv==1.10.0` 拉 Node.js 运行时,新增间接依赖。
  - 首次 `uv sync` 碰到 Windows 临时文件"拒绝访问"(PE 资源写入被拦,可能是 Defender / AV 扫描);重试一次自恢复。
  - FEATURE.md 步骤 0.2 原本就是"pyright 或 mypy 二选一",选 pyright 在设计范围内,不需要改 FEATURE。

---

## 步骤 1.1 · FastAPI app + admin 心跳

- **开始**:2026-04-21
- **完成**:2026-04-21
- **产出**:
  - `rosetta/server/app.py`:`create_app()` 工厂,mount `/admin` router
  - `rosetta/server/admin/__init__.py`:`admin_router` 聚合 health 子路由
  - `rosetta/server/admin/health.py`:`GET /admin/ping` + `GET /admin/status`(Pydantic 返回模型 `PingResponse` / `StatusResponse`,带 `version` / `uptime_ms` / `providers_count` 占位字段)
  - `rosetta/server/__main__.py`:uvicorn 入口,绑 `127.0.0.1:0`(OS 分配 ephemeral),`access_log=False`
  - `pyproject.toml`:runtime deps 加 `fastapi>=0.115`、`uvicorn[standard]>=0.30`
  - `uv.lock` 更新
- **手动测试结果**:
  - 本地静态检查(基础线不能退化):
    - `uv run ruff check .`:✅
    - `uv run ruff format --check .`:✅ 11 files already formatted
    - `uv run pyright rosetta/`:✅ `0 errors, 0 warnings, 0 informations`
    - `uv run pytest`:✅ `1 passed`
  - 步骤 1 `uv run python -m rosetta.server`:✅ stdout 输出 `Uvicorn running on http://127.0.0.1:51155 (Press CTRL+C to quit)`
  - 步骤 2 `curl /admin/ping`:✅ HTTP 200,body `{"ok":true}`
  - 步骤 3 `curl /admin/status`:✅ HTTP 200,body `{"version":"0.1.0","uptime_ms":531,"providers_count":0}`
  - 步骤 4 kill 进程:✅ server 退出,log 里无异常栈
- **CI 验证**:commit `fd1bc1c` 触发 run 24702026697 → conclusion `success`
  - `check (ubuntu-latest)`:12s ✅
  - `check (windows-latest)`:36s ✅
- **通过判据**:✅ 两个 admin 端点均返回 200,server 能正常启停,CI 两平台绿
- **用户确认**:2026-04-21 · "验证通过"
- **偏差 / 备注**:
  - 测试用 bash `kill $PID` 强杀(Windows git bash 的 kill 对 Windows 进程走 TerminateProcess),没走 Uvicorn 的优雅关闭流程。`Ctrl+C` 会触发优雅关闭;阶段 1.4 的 `graceful_shutdown` 才真正落地完整链路。当前 kill 时 log 没有 "Shutting down" 行是正常的。
  - `providers_count=0` 是占位,阶段 1.2 引入 DB 后真查表。
  - `uvicorn` 实装 0.44.0、`fastapi` 最新、带来的间接依赖:starlette 1.0.0 / watchfiles 1.1.1 / websockets 16.0 / typing-inspection 0.4.2 等。

---

## 步骤 1.2 · SQLite + providers CRUD(最小集)

- **开始**:2026-04-21
- **完成**:2026-04-21
- **产出**:
  - `rosetta/server/db/__init__.py`(空)
  - `rosetta/server/db/migrations/__init__.py`(空)
  - `rosetta/server/db/migrations/001_init.sql`:providers / routes / logs 三张表 DDL + `idx_logs_created_at` 索引 + `PRAGMA user_version = 1`
  - `rosetta/server/db/models.py`:SQLAlchemy 2.x 声明式 `Base` + `Provider` / `Route` / `LogEntry`(`Mapped[T]` 注解 + pyright strict 兼容)
  - `rosetta/server/db/session.py`:
    - `DEFAULT_DB_PATH = ~/.rosetta/rosetta.db`
    - `init_db()`:创建目录 → 读 `PRAGMA user_version` → 为 0 时跑 `001_init.sql` → 建 async engine / session_maker;版本比代码支持的更新则拒启动
    - `dispose_db()`:释放连接池
    - `get_session()`:FastAPI 依赖,yield 一个 AsyncSession
    - `count_providers()`:给 /admin/status 用
  - `rosetta/server/admin/providers.py`:`GET /admin/providers`(list)+ `POST /admin/providers`(create,409 冲突;`type=custom` 要求必须带 base_url);`ProviderOut` **不暴露 api_key**
  - `rosetta/server/admin/__init__.py`:挂 providers router
  - `rosetta/server/admin/health.py`:status 端点实时查 providers_count
  - `rosetta/server/app.py`:`lifespan` 里 `init_db` / `dispose_db`
  - `pyproject.toml`:deps 加 `sqlalchemy[asyncio]>=2.0`、`aiosqlite>=0.19`
  - `uv.lock`(+ sqlalchemy 2.0.49 / aiosqlite 0.22.1 / greenlet 3.4.0)
- **手动测试结果**:
  - 本地静态检查:ruff check ✅ / ruff format ✅ 16 files / pyright ✅ 0 errors / pytest ✅ 1 passed
  - 清理旧 `~/.rosetta/rosetta.db`(fresh run)
  - 步骤 1-3 起 server + POST + GET:
    - POST 返回 201,body `{"id":1,"name":"test-provider","type":"anthropic","base_url":null,"enabled":true,"created_at":"2026-04-21T03:30:48.703688"}`
    - GET 返回含 test-provider 的数组,HTTP 200
  - 步骤 4-5 kill + restart + GET:✅ 重启后仍能看到 test-provider(持久化生效)
  - 步骤 6 `PRAGMA user_version`:✅ `1`
  - 步骤 7 logs 表索引:✅ `idx_logs_created_at` 存在
  - 额外验证:`GET /admin/status` 返回 `providers_count=1`(实时查表,非硬编码);响应体**不含 api_key** 字段(ProviderOut schema 没定义)
- **通过判据**:✅ 持久化 / user_version=1 / 索引存在 / api_key 不泄漏 / providers_count 实时
- **用户确认**:(待填)
- **偏差 / 备注**:
  - 用 `aiosqlite` 直连跑 migrations(非 SQLAlchemy):`executescript` 能一次性跑多语句 + `PRAGMA`;SQLAlchemy 的 `conn.execute` 对多语句和 PRAGMA 支持不佳。
  - `Provider.type` 声明 `Mapped[str]`(非 `Literal`),`ProviderCreate.type` 在 Pydantic 层用 `Literal[...]` 做值域校验。ORM 层保持通用 `str`,避免 SA Mapped 与 typing.Literal 的互操作坑。
  - `Provider.created_at` Python 默认值 `datetime.now(UTC)`;SQL 迁移里也有 `DEFAULT CURRENT_TIMESTAMP` 兜底(走 ORM 时 Python 默认优先,走原生 SQL 时 SQLite 默认兜底)。
  - 响应里 `created_at` 是 naive ISO 格式(没带时区后缀),Pydantic 对 `datetime.now(UTC)` 的默认序列化就是这样。若后续 GUI 需明示时区,在 `ProviderOut` 里加 `@field_serializer` 即可,v0 不做。

---

## 修订 · 1.2 · migrations 改走全 SQLAlchemy

- **变更时间**:2026-04-21
- **触发**:用户要求统一 DB 入口,不让 `aiosqlite` 出现在代码里
- **影响范围**:`rosetta/server/db/session.py` 一个文件
- **改动**:
  - 删除 `import aiosqlite` 和 `aiosqlite.connect(...)` 直连代码
  - 新增 `_split_sql_statements(sql)` 工具函数:跳过 `--` 开头整行注释,按 `;` 切分,过滤空白
  - `_maybe_run_migrations(engine)`:
    - 用 `engine.connect()` 执行 `PRAGMA user_version` 读版本
    - 用 `engine.begin()` 在事务里 `conn.execute(text(stmt))` 逐条跑 DDL 和最后的 `PRAGMA user_version = 1`
  - `aiosqlite` 仍在 `pyproject.toml` 的 runtime deps 里(SQLAlchemy 的 `sqlite+aiosqlite://` 驱动运行时需要),但**不在代码里 import**
- **重新验证(本地)**:
  - ruff check / format / pyright / pytest 全绿
  - 清 `~/.rosetta/rosetta.db` 后起 server:POST /admin/providers → 201;GET /admin/providers → 返回含 test-provider;GET /admin/status → providers_count=1
  - `PRAGMA user_version` = 1 ✅
  - `idx_logs_created_at` 索引存在 ✅
  - 三张业务表齐:providers / routes / logs(+ sqlite_sequence 是 SQLite 为 AUTOINCREMENT 自动建的)
- **重新验证(CI)**:未 push(按新规则等用户手动确认)
- **用户确认**:2026-04-21 · "开始执行下一步"(随 `b8ba68c` push 后一并隐式确认)
- **备注**:
  - `_split_sql_statements` 只处理"整行注释"和"分号切分",不处理 `;` 在字符串字面量内的边缘情况;当前 migration 文件结构简单,无此情况;将来若 migration 里出现 `INSERT INTO ... VALUES ('a;b')` 类字符串再强化。
  - PRAGMA `user_version = 1` 在 SQLAlchemy `engine.begin()` 事务内执行有效:SQLite 的 user_version 设置本身是事务性的,transaction commit 后才真正落盘,和 DDL 语义一致。

---

## 修订 · 1.2 · migrations runner 改为通用目录扫描(支持 002+)

- **变更时间**:2026-04-21
- **触发**:原 runner 硬编码跑 `001_init.sql`,无法支持后续 `002_*.sql` 自动升级。用户讨论"如何加字段"时发现此缺陷,提前修复。
- **影响范围**:`rosetta/server/db/session.py`
- **改动**:
  - 新增 `_list_migrations()`:扫 `migrations/` 下 `[0-9][0-9][0-9]_*.sql` 模式的文件,按编号升序返回 `[(N, path), ...]`;检测编号重复并报错
  - `_maybe_run_migrations(engine)`:
    - 启动时自检 `CURRENT_SCHEMA_VERSION == max(migrations[*].N)`,不一致报错(防止程序员改 const 忘了加 SQL 文件,或反之)
    - 读 `PRAGMA user_version` = `current`
    - 按顺序跑所有 `N > current` 的 migration(**每个独立事务**,任一失败不影响之前已成功的)
- **升级场景示意**(未来真加字段时):
  - 老用户 DB `user_version=1` → 启动时只跑 `002+` 的新文件 → 升到 `2`
  - 新用户空 DB `user_version=0` → 启动时跑 `001+002+...`
  - 把新代码指向"更新"的 DB(`user_version=3` 但代码只认到 2) → 拒启动(可能是降级误操作)
- **重新验证(本地)**:
  - ruff / pyright / pytest 全绿
  - 清 `~/.rosetta/rosetta.db` 后 fresh 启动:POST/GET/status 正常,`user_version=1`,三表齐
- **重新验证(CI)**:未 push
- **用户确认**:2026-04-21 · "开始执行下一步"(随 `b8ba68c` push 后一并隐式确认)
- **备注**:
  - 本次**未加**针对 migration 扫描器的单测(如"扫出 001_init.sql"/"重复编号报错"/"空目录报错")。属于可补但非必须,后续可作为"1.2 补强"加进 tests/db/。
  - 第 `NNN` 位固定 3 位,最大 999 条 migration,v0 远超够用。超过时改 glob pattern。
  - SQL 文件的"行内注释"(如 `type TEXT NOT NULL, -- anthropic / ...`)不被过滤:只过滤以 `--` 开头的整行注释。SQLite 解析器自己会处理行内注释。

---

## 步骤 1.3 · 三格式入口(同格式直通,无翻译)

- **开始**:2026-04-21
- **完成**:2026-04-21
- **产出**:
  - `rosetta/shared/formats.py`:`Format` 枚举(messages/completions/responses)、`UPSTREAM_PATH` 映射、`DEFAULT_BASE_URL`(provider.type → 官方 base_url 兜底表)
  - `rosetta/server/dataplane/__init__.py`:`dataplane_router` 聚合
  - `rosetta/server/dataplane/routes.py`:`POST /v1/messages`、`POST /v1/chat/completions`、`POST /v1/responses`(501);`_pick_provider()` 硬编取第一个 enabled;`_is_stream(body)` 解析 JSON 的 `stream` 字段兜底
  - `rosetta/server/dataplane/forwarder.py`:全局 `httpx.AsyncClient`(lifespan 管);`forward()` 按 `is_stream` 分派到 `_forward_once`(普通 POST)或 `_forward_stream`(`client.send(stream=True)` + `StreamingResponse`);auth header 按 provider.type 分(anthropic → `x-api-key` + `anthropic-version`,其余 → `Authorization: Bearer`);`httpx.RequestError` → 502;上游非 2xx 在流式路径会读完 body 转成非流式错误响应
  - `rosetta/server/app.py`(改):lifespan 增加 `init_client` / `dispose_client`;mount `dataplane_router`
  - `pyproject.toml`(改):runtime deps 加 `httpx>=0.28`
  - `uv.lock` 更新(新增 httpx 0.28.1 / httpcore 1.0.9 / certifi 2026.2.25)
  - `tests/mock_upstream.py`:本地假上游,`POST /v1/messages` 模拟 Anthropic(非流 + SSE 8 事件),`POST /v1/chat/completions` 模拟 OpenAI(非流 + SSE chunks + `[DONE]`);`python -m tests.mock_upstream --port 8765` 启动
- **手动测试结果**:
  - 本地静态检查:ruff check ✅ / ruff format ✅ 21 files / pyright ✅ 0 errors / pytest ✅ 1 passed
  - 无 provider 请求 /v1/messages:✅ HTTP 503 "没有 enabled 的 provider"
  - 注册 mock 为 provider(`type=anthropic, base_url=http://127.0.0.1:8765`):✅ 201
  - `POST /v1/messages` 非流式:✅ 200,返回 mock Anthropic-shape JSON(`msg_mock_001`)
  - `POST /v1/messages` 流式:✅ 200,text/event-stream,逐事件透传 `message_start` / `content_block_*` / `message_delta` / `message_stop`
  - `POST /v1/chat/completions` 非流式:✅ 200,mock OpenAI-shape JSON(`chatcmpl_mock_001`)
  - `POST /v1/chat/completions` 流式:✅ 200,逐 chunk + 末尾 `data: [DONE]`
  - `POST /v1/responses`:✅ HTTP 501 "/v1/responses 阶段 2.5 才实现"
- **通过判据**:✅ 三格式端点路由正确、SSE 透传不缓冲、provider 兜底 503、responses 501、auth header 按 type 切换
- **用户确认**:2026-04-21 · "通过"
- **偏差 / 备注**:
  - **验证方案**:原 FEATURE 要求用真 API key 跑 anthropic/openai SDK 冒烟;实际改为**本地 mock upstream + curl**(内网可跑、零外网依赖、错误路径可构造)。FEATURE 未改,偏差记在这里。
  - **未做的扩展**:没建 `tests/smoke_forward.py` 或 pytest 集成测试;验证走人肉 curl。pytest 集成测试(fixture 启动 mock + rosetta + 回归)留到阶段 2 翻译层一起建更划算(有真正需回归的翻译逻辑)。
  - **FastAPI 坑**:`JSONResponse | StreamingResponse` 作为 endpoint 的 return type 注解会触发 FastAPI 的 response_model 推断并报错,加 `response_model=None` 绕开。
  - **auth header 精度**:1.3 阶段所有 /v1/* 请求都用 DB 里的 `provider.api_key`,没做客户端 `x-api-key` 透传优先。FEATURE 3.2 会补。当前 mock 不校验 auth,功能验证不受影响。
  - **provider 选择**:`_pick_provider` 硬编"第一个 enabled",不看 format 和上游 type 匹配。意味着若第一个 provider 是 anthropic,客户端打 /v1/chat/completions 也会用 x-api-key + anthropic-version 发给该上游——在 mock 场景工作,对真 OpenAI 上游会 401。这是 1.3 的**已知简化**,阶段 3.1 路由表接入后消失。
  - **实装 deps**:httpx 0.28.1 + httpcore 1.0.9 + certifi 2026.2.25;bash `rm ~/.rosetta/rosetta.db` 在 Windows 报 "Device or resource busy" 时,rosetta server 仍能正常启动跑 migrations —— 初步判断是 git bash rm 行为问题,不是真 SQLite 锁,后续阶段 1.4 若再碰到同现象再深查。
