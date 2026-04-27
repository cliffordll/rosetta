# 测试 → 发布全流程

> 目标:从"代码改完"到"GitHub Release 上有可下载的 CLI / installer"全流程清单。
> 读完知道每一步动什么文件、跑什么命令、谁(本地 / CI)在做、产物落在哪。
>
> 日常调试 / 手动产 exe 走 [`desktop-run.md`](./desktop-run.md);本文只讲正式 release。

---

## 速览:七步从 main 到 Release

```
┌───────────────────────────┬──────────────┬─────────────────────────────────┐
│ 步骤                      │ 谁执行       │ 关键产物                        │
├───────────────────────────┼──────────────┼─────────────────────────────────┤
│ 1. 本地静态检查 + 测试    │ 开发机       │ 干净 working tree               │
│ 2. bump 版本号(7 处)    │ publish.py   │ pyproject.toml / Cargo.toml 等  │
│ 3. 本地全量构建验证(可选)│ publish.py   │ dist/rosetta-<ver>/             │
│ 4. commit + push 版本号   │ 开发者       │ origin/main 推进一格            │
│ 5. 打 tag 并推送          │ publish.py   │ origin 上的 vX.Y.Z              │
│ 6. CI release.yml 自动跑  │ GitHub       │ GitHub Release + assets         │
│ 7. 验证下载 / installer   │ 开发者 + 用户│ Release 页 SmartScreen 走一遍   │
└───────────────────────────┴──────────────┴─────────────────────────────────┘
```

每步结束都有"验证"动作,通过再进下一步。中途任意一步红 → **回到上一步修**,不要硬推。

---

## 阶段 1 · 本地静态检查 + 测试

每次 release 前在开发机过一遍,**与 CI 一致**(`.github/workflows/ci.yml:34-44`):

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright rosetta/
uv run pytest -q

# 前端
bun run --filter=@rosetta/app typecheck
```

CI 只在 Windows + Ubuntu 跑 Python 这套;前端 typecheck 目前**没进 CI**,本地不漏掉,
否则 Tauri build 阶段才暴露问题(慢)。

✅ **通过条件**:四条全 0 error,working tree 干净(`git status` 空)。

---

## 阶段 2 · bump 版本号

版本号在 7 个文件里都要写一遍(详见[附录 A](#附录-a-7-处版本号)),手动改极易漏。
`scripts/publish.py` 一次性同步:

```bash
# 显式新版本
uv run python scripts/publish.py bump 0.3.0

# 或自动递增(基线必须是干净 X.Y.Z,不带 -rc1 / +meta)
uv run python scripts/publish.py bump patch    # 0.2.0 → 0.2.1
uv run python scripts/publish.py bump minor    # 0.2.0 → 0.3.0
uv run python scripts/publish.py bump major    # 0.2.0 → 1.0.0

# 校验 7 处一致(脚本自带,bump 末尾会跑;手动 ad-hoc 检查也用这个)
uv run python scripts/publish.py check
```

bump 后**锁文件不会自动更新**,跑一下:

```bash
uv sync                    # uv.lock
bun install                # bun.lock
# Cargo.lock 在下次 cargo / tauri build 时自动刷新,不必单独跑
```

✅ **通过条件**:`publish.py check` 显示 7 处都是新版本号;`git diff` 只动版本号 + 锁文件。

---

## 阶段 3 · 本地全量构建验证(强烈建议)

CI 也会构,但本地先跑一次能在 5 分钟内知道是不是版本号 / 配置 / sidecar 有断的,
避免 push tag 后 CI 跑 15 分钟才报错、tag 还得回收。

```bash
# 不出 installer:产 CLI exe + server exe + 桌面 exe(快,验证编译链通)
uv run python scripts/publish.py build

# 完整发布产物:上面 + NSIS installer + updater latest.json
uv run python scripts/publish.py build --installer
```

产物归集在 `dist/rosetta-<ver>/`(`scripts/publish.py:15-24`):

```
dist/rosetta-0.3.0/
├── rosetta.exe                     CLI
├── rosetta-server.exe              server / 桌面 sidecar(同一份)
├── rosetta-desktop.exe             桌面壳
├── Rosetta_0.3.0_x64-setup.exe     NSIS installer (--installer 才有)
└── latest.json                     updater manifest (--installer 才有)
```

✅ **通过条件**(本机 smoke):

- 双击 `rosetta-desktop.exe`,窗口能起,Dashboard 显示版本号 = 新版本号
- `rosetta.exe chat --help` 不报错
- `rosetta-server.exe` 启动后 `curl http://127.0.0.1:<port>/admin/status` 返回 200,`version` 字段对得上
- `--installer` 跑过的话,装一遍 setup.exe,装完进开始菜单能起,卸载干净

⚠️ 没过先回阶段 2 修(常见:tauri.conf.json 改坏了 / sidecar 没同步)。

---

## 阶段 4 · 提交版本号变更

用户走自己平时的 commit + push 节奏。建议把 bump 单独成一个 commit:

```bash
git add pyproject.toml rosetta/__init__.py package.json packages/*/package.json \
        packages/desktop/tauri/Cargo.toml packages/desktop/tauri/tauri.conf.json \
        uv.lock bun.lock packages/desktop/tauri/Cargo.lock
git commit -m "chore: bump 0.3.0"
# 等用户明确指令再 push(参考 CLAUDE.md 的 commit / push 两道 gate)
```

✅ **通过条件**:`origin/main` 已包含 bump commit,**且本地 working tree 干净**(打 tag 前必须干净,否则 tag 指向半成品)。

---

## 阶段 5 · 打 tag 并推送(触发 CI)

`release.yml` 的触发条件是 `push tags: v*`(`.github/workflows/release.yml:5-6`)。
**tag 名格式必须是 `vX.Y.Z`**(以 `v` 开头),否则 workflow 不会触发。

下面两条路径**等效**,任选一条:

### 路径 A · `publish.py`(推荐)

封装了"先 check 7 处版本号一致 → 再打 tag",防止打到错位的 commit 上:

```bash
# 1) 仅本地打 tag(脚本自动用当前版本号 vX.Y.Z;版本不一致会直接 fail 退出)
uv run python scripts/publish.py tag create

# 2) 一步到位:本地打 + 推 origin → 触发 release.yml
uv run python scripts/publish.py tag create --push

# 打错了要回收(还没人下载时)
uv run python scripts/publish.py tag delete           # 只删本地
uv run python scripts/publish.py tag delete --push    # 删本地 + origin
```

### 路径 B · 原生 git 命令(不依赖脚本)

CI 环境 / 不想跑 Python 时用这套。**自己保证版本号一致**(可先跑一次 `publish.py check`):

```bash
# 1) 打 annotated tag(-a 带消息;轻量 tag 也能触发 CI 但 git 历史不带 metadata)
git tag -a v0.3.0 -m "Release 0.3.0"

# 2) 推送到 origin
git push origin v0.3.0

# 或一次性打 + 推
git tag -a v0.3.0 -m "Release 0.3.0" && git push origin v0.3.0

# 查看本地 / 远端已有的 release tag
git tag -l "v*"                          # 本地
git ls-remote --tags origin "refs/tags/v*"   # 远端

# 打错了要回收(本地 + 远端;GitHub Release 草稿要手动到 Releases 页删)
git tag -d v0.3.0                        # 删本地
git push origin --delete v0.3.0          # 删远端
```

> ⚠️ **不要 force push 已发布的 tag**(`git push -f origin v0.3.0`):GitHub Release 已挂的
> assets 不会因 tag 移动而更新,会出现"tag 指向 commit X、Release 内容来自 commit Y"的错位。
> 需重打就走"先 delete 再 create 新版本号"的路。

✅ **通过条件**:`https://github.com/cliffordll/rosetta/actions` 看到 `Release` workflow 已开始跑,branch 列显示 `v0.3.0`。

---

## 阶段 6 · CI release.yml 自动跑

完整流程在 `.github/workflows/release.yml`,分两个 job:

### Job 1 · `python-exe`(`release.yml:17-59`)

Windows runner 上:

1. `uv sync --frozen --group build`
2. **release 兜底**:`ruff check` + `pytest -q`(比 ci.yml 少跑 pyright 节省 ~30s)
3. `python scripts/build.py --sync-sidecar` → 产 `dist/rosetta.exe` + `dist/rosetta-server.exe`,且把 server exe 拷到 `packages/desktop/tauri/binaries/rosetta-server-<triple>.exe` 给下个 job 用
4. 上传 artifact `rosetta-python-exes`(给 desktop-installer 复用)
5. `softprops/action-gh-release@v2` 把 CLI / server exe 直接挂到 GitHub Release(`generate_release_notes: true` 自动写 release notes)

### Job 2 · `desktop-installer`(`release.yml:62-119`)

依赖 Job 1。Windows runner 上:

1. setup-bun + dtolnay/rust-toolchain + Swatinem/rust-cache(目标 `packages/desktop/tauri/target`)
2. `bun install --frozen-lockfile`
3. `actions/download-artifact@v4` 把 sidecar 下回来,放回 `binaries/`
4. `tauri-apps/tauri-action@v0` 跑 build,产 NSIS installer + `latest.json`,自动挂 Release(`includeUpdaterJson: true`)

签名走环境变量(`release.yml:103-110`):

| Secret | 用途 | 未配置时行为 |
|---|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` + `_PASSWORD` | Tauri updater 签名(ed25519)| `latest.json` 无签 → 自动更新链路不工作,但 installer 能装 |
| `WINDOWS_CERTIFICATE` + `_PASSWORD` | Authenticode(Windows 数字证书)| installer 无签 → SmartScreen 警告"未知发布者",可"仍要运行" |

> 这俩 secret **未在 repo 里配置**(参考 `docs/FEATURE.md` §8.2 / §8.3 进度)。
> 当前发出去的 installer 用户首次运行会撞 SmartScreen,属预期。要消警告需用户购买
> 签名证书并配进 GitHub Secrets。

✅ **通过条件**:两个 job 都绿,Release 页面有 5 个 asset:`rosetta.exe` / `rosetta-server.exe` / `rosetta-desktop.exe` / `Rosetta_<ver>_x64-setup.exe` / `latest.json`。

---

## 阶段 7 · 验证 Release

下载页:`https://github.com/cliffordll/rosetta/releases/tag/vX.Y.Z`

最少跑这几步:

1. **下 `rosetta.exe`** → `rosetta.exe chat --help` 能输出
2. **下 `Rosetta_<ver>_x64-setup.exe`** → 装一遍(SmartScreen 警告点"仍要运行"),装完启动,Dashboard 显示对的版本号,Chat / Upstreams / Logs 三个 tab 都能开
3. **`curl https://github.com/cliffordll/rosetta/releases/latest/download/latest.json`** → 返回的 JSON `version` 字段是新版本(updater 端点正确)

⚠️ 任何一步不对,**不要立即重打同名 tag**(GitHub Release 不允许覆盖同名 asset,会报错)。
要么 bump patch 重发,要么按上一节"打错了要回收"的流程清掉再打。

---

## 附录 A · 7 处版本号

source-of-truth 散在 7 个文件里(`scripts/publish.py:80-116`):

| 文件 | 字段 | 用途 |
|---|---|---|
| `pyproject.toml` | `[project] version` | Python 包元数据(PyPI / hatchling 打包用,目前未发 PyPI) |
| `rosetta/__init__.py` | `__version__` | server `/admin/status` API 输出的版本字符串 |
| `package.json` | `version` | npm workspace root |
| `packages/app/package.json` | `version` | 前端 React 包 |
| `packages/desktop/package.json` | `version` | 桌面 workspace 包 |
| `packages/desktop/tauri/Cargo.toml` | `[package] version` | 桌面 exe 在 Windows 文件属性里显示的版本 |
| `packages/desktop/tauri/tauri.conf.json` | `version` | NSIS installer 文件名 + updater `latest.json` 比对版本 |

差一处都会出现"installer 名是 0.3.0、`/admin/status` 显示 0.2.0"这种诡异错位。
**永远走 `publish.py bump`,不要手改。**

---

## 附录 B · 何时只跑 build.py、何时跑 publish.py

| 场景 | 用 |
|---|---|
| 改了 server 代码,要测一下 sidecar 是不是真就位了 | `scripts/build.py --target server --sync-sidecar` |
| 改了 CLI 代码,只想要新的 `rosetta.exe` | `scripts/build.py --target cli` |
| 任何"产个完整版给人用"的场景 | `scripts/publish.py build [--installer]` |
| 改版本号 / 准备发版 / tag 操作 | `scripts/publish.py {check,bump,tag}` |

`build.py` 是底层 PyInstaller 驱动;`publish.py` 包了 build.py + tauri build + 归集 + 版本号管理 + tag。日常调试用底层,正式发版用 publish。

---

## 附录 C · 故障排查速记

| 症状 | 可能原因 | 处理 |
|---|---|---|
| `publish.py bump` 报 "未匹配到版本号 pattern" | 哪个文件 manual 改坏了首行版本号格式 | `git diff` 看哪行,恢复成 `version = "X.Y.Z"` 标准格式 |
| `publish.py build` 报 "找不到桌面 exe" | beforeBuildCommand 的前端 build 失败了 / Tauri 没装 Rust | 看终端往上滚 tauri build 输出;先在 packages/desktop 跑 `bun run tauri build --no-bundle` 单独排错 |
| CI release.yml 第一个 job 红 | 大概率版本号不一致 / pytest 红 | 看 Actions 日志,在本地复现修;**不要直接 force push tag**,删 tag → 重 bump → 重打 |
| Installer 装完启动闪退 | sidecar 没就位 / sidecar 名带 triple 错位 | 看 `%LOCALAPPDATA%\Rosetta\logs\`(若有)或在终端起 `rosetta-desktop.exe` 看 stderr |
| `latest.json` 404 | updater secret 没配 → tauri-action 跳过了签名 → `latest.json` 没产 | 配 `TAURI_SIGNING_PRIVATE_KEY` 后重打一个 patch tag(0.3.0 → 0.3.1) |

---

## 相关文档

- [`docs/DESIGN.md`](../DESIGN.md) §6 / §7 — 桌面分发架构
- [`docs/FEATURE.md`](../FEATURE.md) §6 / §7 / §8 — 打包 / 桌面 / Release 任务进度
- [`docs/guides/desktop-run.md`](./desktop-run.md) — 不走 NSIS 的本地跑桌面端
- [`scripts/publish.py`](../../scripts/publish.py) 顶部 docstring — 命令一览(本文 source-of-truth)
- [`.github/workflows/release.yml`](../../.github/workflows/release.yml) — CI release pipeline 真源
