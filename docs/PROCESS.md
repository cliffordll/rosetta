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
