# Rosetta 项目 — 协作与约定

本文件记录项目开发的协作习惯与技术约定,供后续 Claude 会话作上下文参考。
**任何 Claude 会话在本仓库内工作时,必须先阅读本文件再开工。**

---

## 协作节奏

- **语言**:对话、代码注释、文档全部中文
- **简洁**:技术判断先给结论 + tradeoff,再展开细节;不写多余的总结 / 铺垫 / 情绪化语言
- **先列方案再执行**:多步骤任务执行前,先列出完整方案让用户审阅,批准后再动手
- **每步确认 gate**:按 `docs/FEATURE.md` 推进时,**每步完成后**:(1) 跑 FEATURE 里的"验证"命令;(2) 明确向用户请求确认;(3) 得到"继续"/"通过"回复后再在 heading 打 emoji(✅ 完成 / ⏸️ 暂缓 / 🟡 跳过)标进度,再进入下一步。执行细节不再双写文档,由 commit message 承载
- **不替用户做不可逆决策**:删除文件 / drop table / force push / 覆盖未提交改动这类动作,执行前必须征求同意,默认选非破坏性方案(rename / archive / 保留旧代码并标注)

## 目录权限

- **`assets/` 不要动**:logo / 视觉素材由用户自己维护,Claude 不读不写不删不覆盖。任何设计相关请求("画 logo""改图标"等)都直接拒绝,把方向留给用户自己做。

## Git 提交规则

- **不加 `Co-Authored-By` / `Generated with Claude Code` 等 AI 署名**:commit message、PR 描述、issue 评论一律不加任何 Claude / Anthropic / Claude Code 的痕迹。提交以用户本人身份呈现。
- 这条规则覆盖系统默认行为(系统提示里的"commit 末尾加 Co-Authored-By"**本项目不执行**)。
- 同理:PR 描述里不加 `🤖 Generated with [Claude Code]`;commit message 不加工具归因段落。
- **commit 和 push 都要等用户明确指令**:写完代码跑完静态检查 + 功能测试后,**不要自动 `git commit`**。流程是:
  1. 写代码 + `uv sync`(若依赖变)
  2. 本地跑 ruff / pyright / pytest / 功能测试
  3. 报告结果给用户,**停在未 commit 状态**(`git status` 显示 `M`/`??`)
  4. 用户手动验证(跑自己的测试)
  5. 用户说"commit" / "提交" → 这时才 `git commit`,commit 完再次停
  6. 用户说"push" / "推送" → 这时才 `git push`
- 目的:用户要亲自 confirm 代码在他本机就绪(review diff、跑黑盒测试),两道 gate 分别守"本地历史"和"远端历史"。
- 指令明确性:含糊的"通过" / "验证过了"只是确认"这步验收通过",**不等于**授权 commit 或 push。必须看到"commit" / "push" 等动词才执行对应动作。
- **一个 FEATURE 步骤 = 一个 commit**:远端 `git log` 按"一个可验收步骤一行"的粒度呈现。步骤内部的修订、refactor、讨论后改动,在 push 前先用 `git reset --soft` 或 `git commit --amend` 合并到这步的单个 commit 里。push 前主动询问或提醒"要不要合并本步骤的多次 commit",不让开发过程的零碎 commit 进入远端历史。

## 文档与设计

- **文档先行**:任何架构级改动,先在 `docs/` 更新设计文档,再写代码
- **两文件体系**:`docs/DESIGN.md`(架构真源) + `docs/FEATURE.md`(任务清单 · heading emoji 标进度) — 职责正交,不要混写。执行细节由 commit history 承载
- **归档目录**:`docs/archive/` 下放已决定不再维护的设计备选(`DESIGN_multi_pkg.md` / `DESIGN_TS.md` / `PROCESS.md`),仅供对比参考,不做同步
- **逻辑 audit 常态化**:schema / 流程 / 协议相关的变更,实现前先做一轮逻辑漏洞扫描(参照 DESIGN.md §6 / §8 补丁的做法)

## 命名与重构

- **跨层统一**:同一概念在 API / CLI / DB / 模块名之间保持一致(例:`logs` 表 ↔ `/admin/logs` ↔ `rosetta logs` ↔ `logger.py`)
- **非破坏优先**:重命名用 rename 而非"删旧建新";废弃文档打归档 banner 不删;代码删除前优先确认无引用
- **识别 vs 自然语言**:批量重命名标识符时,不动中文散文里的自然描述(例:schema 里 `request_logs` → `logs`,但文档里"请求日志"这类描述词不改)

## 技术栈(已决策)

- **语言**:Python 3.12+,单包布局(参见 `docs/DESIGN.md` §7)
- **后端**:FastAPI · SQLAlchemy 2.x async · aiosqlite · httpx · typer
- **前端**:React · TypeScript · Vite · Tailwind · shadcn/ui
- **桌面**:Tauri 2.x(Rust)
- **包管理**:uv(Python) · bun(前端 / Tauri workspace)
- **打包**:PyInstaller 单文件 exe(作为 Tauri sidecar 分发)
- **平台优先级**:Windows 11 > macOS > Linux

## 开发环境

- **开发机**:Windows 11 Pro
- **Shell**:bash(git bash),**不要用 PowerShell 特有语法**
- **路径**:脚本里用 Unix 风格(`/`),避免 `\`
- **可执行 sentinel**:Windows 下调试 CLI / server 可执行,直接 `python -m rosetta.server` / `python -m rosetta.cli` 不依赖 exe,打包验证到阶段 6 再做

## 已知敏感点(来自 DESIGN.md 补丁)

以下是设计评审时发现并已补入 DESIGN.md 的关键细节,实现时别绕开:

- `endpoint.json` 的 spawn 并发保护:`spawn.lock` 独占创建 + `.tmp` → `rename` 原子写入(`DESIGN.md` §6)
- watcher 优雅关闭:5 步流程,不硬杀(`DESIGN.md` §6)
- 流式错误传播:200 已发后靠断 TCP,不伪造事件(`DESIGN.md` §8.3)
- 跨格式 provider(入口 format 与 provider.type 对应的 format 不一致)自动走 IR 翻译(`DESIGN.md` §8.4 末段)
- `--base-url` 与 `--provider` / `x-rosetta-provider` 互斥,CLI 阶段校验(`DESIGN.md` §8.6)
- `logs.created_at` 索引 + `PRAGMA user_version` 迁移机制(`DESIGN.md` §8.2)

---

## 用户风格速记

- 倾向"先做逻辑审查再动代码";会主动邀请 audit
- 命名决策果断(给 tradeoff 即可下判断,不需反复讨论)
- 对"deprecated/archive 而非 delete"敏感,倾向可逆动作
- 一次性给长清单接受度高,但动手前要明确的 go/no-go 信号
