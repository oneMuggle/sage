# Sage Docs Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/superpowers/specs/2026-07-17-docs-cleanup-design.md` 清理 `docs/` 目录,删除 47 个过期文档,修复 2 处编号冲突,新增 1 个子目录 README + 1 个总索引段落。

**Architecture:** 在 main 分支上建 `chore/docs-cleanup-2026-07` 分支,按 7 个原子 commit 顺序执行变更,最后创建 PR 让用户 merge。

**Tech Stack:** git, bash, grep, Markdown

## Global Constraints

- 分支命名:`chore/docs-cleanup-2026-07`(来自项目 `feature-branch-workflow.md` 规则)
- Commit 格式:Conventional Commits(来自 `git-workflow.md`)
- Push 时:`LEFTHOOK=0 git push`(来自项目 memory:lefthook pre-push 偶发失败)
- 仅动 main 分支,不动 release/win7(由后续 cherry-pick PR 处理)
- 每次 commit 后运行相应验证命令(ls/grep)
- 实施前 git 工作区需干净(本次工作前的 package-lock.json 修改不在本 PR 范围,先 git stash)

---

## Task 1: Setup & Branch

**Files:**
- 无文件修改(只切换分支)

**Interfaces:**
- 起点:`main` 分支 HEAD
- 终点:`chore/docs-cleanup-2026-07` 分支创建完成

- [ ] **Step 1: 验证当前在 main 分支**

```bash
git branch --show-current
```

预期: `main`

- [ ] **Step 2: 暂存 package-lock.json 改动(避免污染本 PR)**

```bash
git stash push -m "docs-cleanup-pre-stash" -- package-lock.json
```

预期: `Saved working directory and index state on main: ...`

- [ ] **Step 3: 拉取最新 main**

```bash
git fetch origin main && git pull --rebase origin main
```

预期: `Already up to date.` 或 fast-forward

- [ ] **Step 4: 创建并切换到功能分支**

```bash
git switch -c chore/docs-cleanup-2026-07
```

预期: `Switched to a new branch 'chore/docs-cleanup-2026-07'`

- [ ] **Step 5: 验证分支创建成功**

```bash
git status -sb
```

预期: `## chore/docs-cleanup-2026-07...origin/chore/docs-cleanup-2026-07`(后者可能不存在,正常)

---

## Task 2: 删除 docs/plans/ 26 个过期文件

**Files:**
- Delete: `docs/plans/2026-05-17-ai-agent-desktop-client.md`
- Delete: `docs/plans/2026-05-28_ui-integration-css-variables.md`
- Delete: `docs/plans/2026-05-29_sage-core-features.md`
- Delete: `docs/plans/2026-05-30_llm-wiki.md`
- Delete: `docs/plans/2026-06-01_sage-core-llm-conversation-foundation.md`
- Delete: `docs/plans/2026-06-01_sage-next-features.md`
- Delete: `docs/plans/2026-06-12_llm-wiki-llm-integration.md`
- Delete: `docs/plans/2026-06-17_llm-thinking-display.md`
- Delete: `docs/plans/2026-06-18_drawio-integration.md`
- Delete: `docs/plans/2026-06-19_ai-agent-memory-research.md`
- Delete: `docs/plans/2026-06-19_enhancement-plans-overview.md`
- Delete: `docs/plans/2026-06-19_formal-verification-maps.md`
- Delete: `docs/plans/2026-06-19_mcp-lifecycle-management.md`
- Delete: `docs/plans/2026-06-19_memory-integration-to-chatservice.md`
- Delete: `docs/plans/2026-06-19_memory-optimization-plan.md`
- Delete: `docs/plans/2026-06-19_multi-agent-coordination.md`
- Delete: `docs/plans/2026-06-19_parity-alignment.md`
- Delete: `docs/plans/2026-06-19_philosophy-document.md`
- Delete: `docs/plans/2026-06-19_rag-service-extraction.md`
- Delete: `docs/plans/2026-06-19_shared-core-library.md`
- Delete: `docs/plans/2026-06-19_verification-map-system.md`
- Delete: `docs/plans/2026-06-22_agent-orchestrator-wiring.md`
- Delete: `docs/plans/2026-06-23_optimization-plan-aionui-reference.md`
- Delete: `docs/plans/2026-06-26_llm-wiki-optimization.md`
- Delete: `docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md`
- Delete: `docs/plans/2026-06-26_officecli-integration.md`

**Interfaces:**
- 删除前 grep 确认无外部引用
- 删除后只剩 2 个 plan 文件

- [ ] **Step 1: 删除前 grep 确认引用情况**

```bash
grep -rEn "2026-05-(17|28|29|30)|2026-06-01_|2026-06-12_|2026-06-17_|2026-06-18_|2026-06-19_|2026-06-22_|2026-06-23_|2026-06-26_" docs/ --include="*.md"
```

预期: 列出指向这些文件的引用位置(会在 Task 8 修复)

- [ ] **Step 2: 删除所有 26 个文件**

```bash
git rm \
  docs/plans/2026-05-17-ai-agent-desktop-client.md \
  docs/plans/2026-05-28_ui-integration-css-variables.md \
  docs/plans/2026-05-29_sage-core-features.md \
  docs/plans/2026-05-30_llm-wiki.md \
  docs/plans/2026-06-01_sage-core-llm-conversation-foundation.md \
  docs/plans/2026-06-01_sage-next-features.md \
  docs/plans/2026-06-12_llm-wiki-llm-integration.md \
  docs/plans/2026-06-17_llm-thinking-display.md \
  docs/plans/2026-06-18_drawio-integration.md \
  docs/plans/2026-06-19_ai-agent-memory-research.md \
  docs/plans/2026-06-19_enhancement-plans-overview.md \
  docs/plans/2026-06-19_formal-verification-maps.md \
  docs/plans/2026-06-19_mcp-lifecycle-management.md \
  docs/plans/2026-06-19_memory-integration-to-chatservice.md \
  docs/plans/2026-06-19_memory-optimization-plan.md \
  docs/plans/2026-06-19_multi-agent-coordination.md \
  docs/plans/2026-06-19_parity-alignment.md \
  docs/plans/2026-06-19_philosophy-document.md \
  docs/plans/2026-06-19_rag-service-extraction.md \
  docs/plans/2026-06-19_shared-core-library.md \
  docs/plans/2026-06-19_verification-map-system.md \
  docs/plans/2026-06-22_agent-orchestrator-wiring.md \
  docs/plans/2026-06-23_optimization-plan-aionui-reference.md \
  docs/plans/2026-06-26_llm-wiki-optimization.md \
  docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md \
  docs/plans/2026-06-26_officecli-integration.md
```

预期: 26 行 `rm 'docs/plans/...'`

- [ ] **Step 3: 验证 docs/plans/ 只剩 2 个文件**

```bash
ls docs/plans/
```

预期输出:
```
2026-07-04_chat-tool-path-hardening-from-claw-code.md
2026-07-16_office-features.md
```

- [ ] **Step 4: 提交**

```bash
git commit -m "chore(docs): 删除 docs/plans/ 26 个过期计划

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.1,
通过 git 交叉验证确认所有计划涉及的工作已通过对应 PR merge,
功能点已并入 docs/technical/ 或 docs/user-manual/ 对应章节。

保留 2 个 in-progress 计划:
- 2026-07-04_chat-tool-path-hardening-from-claw-code.md (PR #130 后还有 Phase 2/3)
- 2026-07-16_office-features.md (Phase 1 已合并,Phase 2/3 待实施)"
```

预期: `[chore/docs-cleanup-2026-07 xxxxxx] chore(docs): ...` + `26 files changed, 0 insertions(+), 0 deletions(-)` (因为是 git rm,实际删除)

---

## Task 3: 删除 docs/superpowers/plans/ 21 个历史执行计划

**Files:**
- Delete: `docs/superpowers/plans/` 全部 21 个文件(详见 spec §4.2)

**Interfaces:**
- 删除后 `docs/superpowers/plans/` 为空目录(或保留 `.gitkeep`)

- [ ] **Step 1: 删除 docs/superpowers/plans/ 全部 21 个文件**

```bash
git rm docs/superpowers/plans/*.md
```

预期: 21 行 `rm 'docs/superpowers/plans/...'`

- [ ] **Step 2: 验证目录为空**

```bash
ls docs/superpowers/plans/
```

预期: 空输出(目录还在但没文件)

- [ ] **Step 3: 提交**

```bash
git commit -m "chore(docs): 删除 docs/superpowers/plans/ 21 个历史执行计划

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.2,
这些是 phase 1-8 等已合并的实施计划,信息已通过 git commit + PR
完整保留。git 历史永久存档,文档不再需要。

唯一例外检查:2026-07-10 release-branch-strategy-plan.md
对应 PR #129 已 merged,故也在删除之列。"
```

预期: 21 files changed

---

## Task 4: 合并 technical/24-scheduled-tasks.md 到 24-skills-system.md

**Files:**
- Read: `docs/technical/24-scheduled-tasks.md`(56 行)
- Read: `docs/technical/24-skills-system.md`(595 行)
- Modify: `docs/technical/24-skills-system.md`(添加 §"定时任务"小节)
- Delete: `docs/technical/24-scheduled-tasks.md`

**Interfaces:**
- 合并位置:在 24-skills-system.md 的 "## SKILL.md v2 适配层" 或 "## Slash Command" 章节附近最合理(由实施者决定)
- 保留 24-scheduled-tasks.md 的所有设计意图(定时任务的 schedule/cron/触发器 等)

- [ ] **Step 1: 读取源文件内容**

```bash
cat docs/technical/24-scheduled-tasks.md
```

预期: 看到完整 56 行内容(实施者需理解这些内容以便正确合并)

- [ ] **Step 2: 读取目标文件,定位合并位置**

```bash
grep -n "^## " docs/technical/24-skills-system.md
```

预期: 看到所有 H2 章节标题和行号,选择合并位置

- [ ] **Step 3: 在 24-skills-system.md 添加 "## 定时任务" 小节**

基于 Step 1 的输出,把 24-scheduled-tasks.md 的内容(56 行)整理为统一格式,追加到 24-skills-system.md。添加模板:

```markdown
## 定时任务

> **合并来源**: 原 `docs/technical/24-scheduled-tasks.md`(已删除)。

{原始内容,经格式整理后插入此处。原始 56 行是设计 sketch,实施者需要:
 1. 提取核心设计意图(schedule/cron/触发器模型等)
 2. 用与 24-skills-system.md 现有章节一致的 markdown 风格重写
 3. 引用上文已有的 SKILL.md v2 / Slash Command 概念,避免重复
 4. 加注:"详见 in-progress plan: 2026-07-04_chat-tool-path-hardening-from-claw-code.md"}

合并位置: 在 SKILL.md v2 / Slash Command 章节附近,实施者按原文逻辑自然承接决定具体行号。
```

- [ ] **Step 4: 删除源文件**

```bash
git rm docs/technical/24-scheduled-tasks.md
```

预期: `rm 'docs/technical/24-scheduled-tasks.md'`

- [ ] **Step 5: 验证 24-scheduled-tasks.md 已删除**

```bash
ls docs/technical/24-scheduled-tasks.md 2>&1
```

预期: `ls: cannot access 'docs/technical/24-scheduled-tasks.md': No such file or directory`

- [ ] **Step 6: 提交**

```bash
git add docs/technical/24-skills-system.md
git commit -m "refactor(docs): 合并 24-scheduled-tasks.md 内容到 24-skills-system.md

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.4,
原 24-scheduled-tasks.md 是 56 行设计 sketch,内容已被
24-skills-system.md 的 gating/scripts/dispatch 涵盖。
短文档并入长文档作为'定时任务'小节,删除源文件。"
```

预期: 2 files changed(1 modified + 1 deleted)

---

## Task 5: 重命名 technical/21-win7-lts.md → 31-win7-lts.md

**Files:**
- Rename: `docs/technical/21-win7-lts.md` → `docs/technical/31-win7-lts.md`
- Modify: `docs/technical/README.md`(更新表格条目)
- Modify: 其他文件里指向 `21-win7-lts.md` 的链接(grep 后逐个改)

**Interfaces:**
- 重命名后 technical/ 编号无重号(21 只剩 llm-proxy,31 为 win7-lts)
- 所有 cross-reference 更新

- [ ] **Step 1: 查找所有引用 21-win7-lts.md 的位置**

```bash
grep -rEn "21-win7-lts\.md" docs/ --include="*.md"
```

预期: 列出所有引用位置(README.md + 其他可能文件)

- [ ] **Step 2: git mv 重命名文件**

```bash
git mv docs/technical/21-win7-lts.md docs/technical/31-win7-lts.md
```

预期: 输出 rename 信息

- [ ] **Step 3: 更新 docs/technical/README.md**

找到原表格中 `21` 行的 `21-win7-lts.md` 条目,改为 `31-win7-lts.md`。具体编辑:

原内容(在 README.md 中):
```markdown
| 21   | [Win7 LTS 维护](./21-win7-lts.md)                    | 18 个月归档时间表 / ... |
```

改为:
```markdown
| 31   | [Win7 LTS 维护](./31-win7-lts.md)                    | 18 个月归档时间表 / ... |
```

- [ ] **Step 4: 更新其他文件的引用(基于 Step 1 的 grep 输出)**

对每个 grep 命中的文件,执行:

```bash
# 替换文件中的 21-win7-lts.md 为 31-win7-lts.md
# 用 sed 批量替换(在 git 工作区目录下)
grep -rl "21-win7-lts\.md" docs/ --include="*.md" | xargs sed -i 's|21-win7-lts\.md|31-win7-lts.md|g'
```

预期: 无输出(sed 静默)

- [ ] **Step 5: 验证所有引用已更新**

```bash
grep -rEn "21-win7-lts\.md" docs/ --include="*.md"
```

预期: 空输出(已无引用)

- [ ] **Step 6: 验证 31-win7-lts.md 存在**

```bash
ls docs/technical/31-win7-lts.md
```

预期: 文件存在

- [ ] **Step 7: 提交**

```bash
git add docs/technical/31-win7-lts.md docs/technical/README.md
git add -u docs/
git commit -m "refactor(docs): 重命名 21-win7-lts.md → 31-win7-lts.md 修复编号冲突

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.4,
原 21-llm-proxy.md 和 21-win7-lts.md 共享 21 编号冲突。
21-llm-proxy.md 是更早文档保留原名,21-win7-lts.md 是较新文档
挪到 31(30 之后第一个空闲号)。

同步更新 README.md 表格和所有 cross-reference。"
```

预期: N files changed(1 renamed + 1+ modified)

---

## Task 6: 新增 docs/superpowers/specs/README.md

**Files:**
- Create: `docs/superpowers/specs/README.md`

**Interfaces:**
- README 含目录定位、归档策略、章节目录(14 个 spec 列表)、与其他目录关系

- [ ] **Step 1: 创建 README.md**

```bash
cat > docs/superpowers/specs/README.md <<'EOF'
# Sage 设计 Spec 归档

> 本目录收录 Sage 各功能/阶段的**设计 spec**。功能实施后,spec 保留作为"设计 vs 实际"对比基线。

## 目录定位

- **功能**: 设计阶段的取舍/方案讨论
- **状态**: 即使对应功能已实现,spec 不删除
- **可参考价值**: 对比"设计预期"与"实现实际"的偏差,作为未来重构的参考

## 归档策略

| 阶段 | 操作 |
|---|---|
| spec 阶段 | spec 写入本目录,标 `状态: 设计中` |
| 实施完成 | spec 状态改为 `状态: 已实施`,**保留在本目录** |
| 实施内容并入 docs/ | spec 仍保留;同时新章节并入 `docs/technical/` 或 `docs/user-manual/` 主目录 |

## 章节目录

| 日期 | 标题 | 一句话简介 |
|---|---|---|
| 2026-06-04 | [LLM Pipeline Tool System Design](./2026-06-04-llm-pipeline-tool-system-design.md) | Sage LLM 链路打通 + 工具系统设计 |
| 2026-06-05 | [Sage 质量优化 Design](./2026-06-05-sage-quality-optimization-design.md) | Sage 全栈质量优化设计 |
| 2026-06-22 | [localStorage → Backend Design](./2026-06-22-localstorage-to-backend-design.md) | localStorage 配置存储迁移至后端 SQLite 设计 |
| 2026-06-23 | [Win7 LTS Release Workflow Design](./2026-06-23-win7-lts-release-workflow-design.md) | 双轨 release 工作流（main → Win10+ & release/win7 → Win7 LTS） |
| 2026-06-25 | [aionui-inspired UI Design](./2026-06-25-aionui-inspired-ui-design.md) | Sage AionUi 借鉴方案 — 设计文档 |
| 2026-06-27 | [LLM Wiki Folder Picker Design](./2026-06-27-llm-wiki-folder-picker-design.md) | LLM Wiki 项目创建/打开：原生文件夹选择器 |
| 2026-06-29 | [agentskills.io Spec Conformance Design](./2026-06-29-agentskills-io-spec-conformance-design.md) | AgentSkills.io Spec Conformance Design |
| 2026-06-30 | [Skills Management Delete/Hot-Reload Design](./2026-06-30-skills-management-delete-hotreload-design.md) | Skills 管理: 删除 + 热重载设计 |
| 2026-07-01 | [Skills Load New Design](./2026-07-01-skills-load-new-design.md) | Skills 加载新技能 — Design Spec |
| 2026-07-02 | [Electron Logging Design](./2026-07-02-electron-logging-design.md) | Electron 桌面日志 — Design Spec |
| 2026-07-06 | [Sage Release Tiers Design](./2026-07-06-sage-release-tiers-design.md) | Sage 版本生命周期分级（alpha → beta → preview → stable） |
| 2026-07-08 | [Wiki Streaming Design](./2026-07-08-wiki-streaming-design.md) | Sage LLM Wiki — 流式聊天/摄取接入设计 |
| 2026-07-10 | [Release Branch Strategy Design](./2026-07-10-release-branch-strategy-design.md) | Sage Release Branch 策略（稳定化分支 + 下游消费镜像） |
| 2026-07-17 | [Docs Cleanup Design](./2026-07-17-docs-cleanup-design.md) | Sage 文档整理 (Docs Cleanup) — 设计 Spec |

## 与其他目录关系

| 目录 | 定位 |
|---|---|
| [`docs/plans/`](../../plans/) | **进行中**的实施计划。功能完成后并入主目录并删除(规则见 `feature-development.md`) |
| [`docs/technical/`](../../technical/) | 已归档的**横切关注点**技术文档 |
| [`docs/user-manual/`](../../user-manual/) | 终端用户操作指南 |
| [`docs/superpowers/ideas/`](../ideas/) | 暂不做的零散想法 |
| [`docs/superpowers/plans/`](../plans/) | 已合并的**历史执行计划**(2026-07-17 整理后已清空) |

> 维护规则来源:`feature-development.md`(项目根)。
EOF
```

预期: 文件创建成功

- [ ] **Step 2: 验证文件结构**

```bash
ls -la docs/superpowers/specs/README.md && head -20 docs/superpowers/specs/README.md
```

预期: 文件存在,前 20 行包含标题

- [ ] **Step 3: 提交**

```bash
git add docs/superpowers/specs/README.md
git commit -m "docs(specs): 新增 docs/superpowers/specs/README.md

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.3,
明确 specs/ 目录的'设计归档'定位、归档策略、章节目录(14 个 spec
含本次清理自身)、与其他目录的关系。
新增 14 条目(含 2026-07-17 docs-cleanup 自身)。"
```

预期: 1 file changed, N insertions

---

## Task 7: 新增 docs/README.md "子目录总览" 段落

**Files:**
- Modify: `docs/README.md`(在"技术专题"小节后、"核心技术参考"前新增段落)

**Interfaces:**
- 新增段落含 8 个子目录的"定位"+"维护规则"两列

- [ ] **Step 1: 定位插入点**

```bash
grep -n "^## \|^### " docs/README.md | head -30
```

预期: 看到所有 H2/H3 标题,定位"技术专题"和"核心技术参考"的行号

- [ ] **Step 2: 在 docs/README.md 中插入新段落**

基于 Step 1 的输出,在"技术专题"小节(以 `> 完整技术专题目录见` 结尾)后、"核心技术参考"(`### Hermes Agent 参考点`)前,插入:

```markdown
## 📚 docs/ 子目录总览

| 子目录 | 定位 | 维护规则 |
|---|---|---|
| `01-14.md`(根) | 核心技术章节(架构/数据库/记忆/Agent/工具等) | 稳定文档,功能完成后更新对应章节 |
| [`technical/`](./technical/) | 15-30 横切关注点(质量门禁/可观测性/六边形等) | 新功能模块加章节,编号顺延 |
| [`user-manual/`](./user-manual/) | 终端用户操作指南(01-06) | 用户可见功能完成后加章节 |
| [`plans/`](./plans/) | **仅进行中的实施计划** | 功能完成后并入技术手册/用户手册并删除 |
| [`superpowers/ideas/`](./superpowers/ideas/) | 暂不做的零散想法 | 不进 roadmap,不进 specs/ |
| [`superpowers/specs/`](./superpowers/specs/) | 设计 spec 归档(实施后保留作对比基线) | 见同目录 README.md |
| [`philosophy/`](./philosophy/) | 哲学/反模式/决策框架 | 缓慢演化,极少更新 |
| [`verification/`](./verification/) | 9 大目标验证地图(g001-g009) | 见同目录 README.md |

> 维护规则来源:`feature-development.md`(项目根)。
```

- [ ] **Step 3: 验证插入成功**

```bash
grep -A 12 "docs/ 子目录总览" docs/README.md
```

预期: 看到刚插入的 8 行表格 + 注脚

- [ ] **Step 4: 提交**

```bash
git add docs/README.md
git commit -m "docs(readme): 新增 'docs/ 子目录总览' 段落

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.5,
为新贡献者提供 docs/ 完整结构总览,含 8 个子目录的定位与维护规则。"
```

预期: 1 file changed, +12 insertions(表格 + 注脚)

---

## Task 8: 失效链接审计与修复

**Files:**
- Modify: 多个文件(基于 grep 输出的命中位置)

**Interfaces:**
- grep 失效链接命令返回空
- 不破坏任何现有的正确链接

- [ ] **Step 1: 扫描失效链接**

```bash
grep -rEn "\(.*\.md\)" docs/ --include="*.md" | \
  grep -E "(2026-05-(17|28|29|30)|2026-06-(01|12|17|18|19|22|23|26))_[a-z_-]+\.md|2026-06-26_officecli-integration\.md|24-scheduled-tasks\.md|21-win7-lts\.md"
```

预期: 列出所有指向已删除文件的链接

- [ ] **Step 2: 分类处理**

基于 Step 1 输出,对每个命中:
- 若指向**已删 plan** → 删除整行(或该 plan 涉及的整段)
- 若指向 `24-scheduled-tasks.md` → 改为 `24-skills-system.md#定时任务`(若锚点存在)或 `24-skills-system.md`
- 若指向 `21-win7-lts.md` → 应已被 Task 5 处理,若无输出则跳过

- [ ] **Step 3: 修复每处失效链接**

对每个命中文件,使用 Edit 工具或 sed 修复。具体修复内容由实施者基于 Step 1 输出决定。

- [ ] **Step 4: 验证 grep 命令现在返回空**

```bash
grep -rEn "\(.*\.md\)" docs/ --include="*.md" | \
  grep -E "(2026-05-(17|28|29|30)|2026-06-(01|12|17|18|19|22|23|26))_[a-z_-]+\.md|2026-06-26_officecli-integration\.md|24-scheduled-tasks\.md|21-win7-lts\.md"
```

预期: 空输出

- [ ] **Step 5: 提交**

```bash
git add -u docs/
git commit -m "fix(docs): 修复 26 个 plan 删除 + 1 个 technical 重命名后的失效链接

按 docs/superpowers/specs/2026-07-17-docs-cleanup-design.md §4.6,
对指向已删文件 / 旧文件名的 markdown 链接逐一修复或删除。
grep 验证命令现已返回空。"
```

预期: N files changed(N 由失效链接分布决定,通常 0-5)

---

## Task 9: 推送并创建 PR

**Files:**
- 无文件修改(纯 git 操作)

**Interfaces:**
- 分支推送到 origin
- PR 在 GitHub 上创建

- [ ] **Step 1: 验证所有 commit 已在本地**

```bash
git log --oneline main..HEAD
```

预期: 显示 7 个 commit(chore/docs 删除 + superpowers/plans 删除 + 24-scheduled-tasks 合并 + 21-win7-lts 重命名 + specs README + docs README 总览 + 失效链接修复)

- [ ] **Step 2: 推送分支(使用 LEFTHOOK=0 规避偶发 pre-push 失败)**

```bash
LEFTHOOK=0 git push -u origin chore/docs-cleanup-2026-07
```

预期: `remote: Create pull request...` 或类似成功消息

- [ ] **Step 3: 创建 PR**

```bash
gh pr create --base main --title "chore(docs): 整理 docs 目录 - 删除 47 个过期文件 + 修复 2 处编号冲突 + 新增 specs README + docs 总索引" --body "$(cat <<'EOF'
## 摘要

按 [docs/superpowers/specs/2026-07-17-docs-cleanup-design.md](docs/superpowers/specs/2026-07-17-docs-cleanup-design.md) 整理 docs/ 目录。

## 改动

### 删除(共 47 个文件)
- `docs/plans/` 26 个过期实施计划(功能已通过对应 PR merge)
- `docs/superpowers/plans/` 21 个历史执行计划(信息已通过 git commit 永久存档)

### 保留(共 2 个)
- `docs/plans/2026-07-04_chat-tool-path-hardening-from-claw-code.md`(Phase 2/3 待实施)
- `docs/plans/2026-07-16_office-features.md`(Phase 2/3 待实施)

### 编号冲突修复
- `docs/technical/21-win7-lts.md` → `31-win7-lts.md`(挪到 30 之后第一个空闲号)
- `docs/technical/24-scheduled-tasks.md` 内容并入 `24-skills-system.md` 后删除

### 新增
- `docs/superpowers/specs/README.md`(14 个 spec 索引 + 归档策略说明)
- `docs/README.md` "子目录总览"小节(8 个子目录的定位与维护规则)

### 修复
- 失效链接审计与修复

## 验证

- [x] docs/plans/ 只剩 2 个文件
- [x] docs/superpowers/plans/ 为空目录
- [x] docs/technical/ 编号无重号(21 唯一、24 唯一)
- [x] docs/superpowers/specs/README.md 存在
- [x] docs/README.md 含子目录总览小节
- [x] grep 失效链接命令返回空

## 后续(非本 PR 范围)

- release/win7 是否需同步清理: 另起 cherry-pick PR
- docs/01-14.md 核心章节陈旧引用审计: 后续内容 review PR
- 巨型文件拆分: 出现维护痛点时启新 spec

## 测试计划

纯文档变更,无代码逻辑改动。CI 应自然过。AI review 时关注:
- 失效链接是否还有遗漏
- 编号变动是否影响其他文档的引用
- specs/README.md 的归档策略描述是否准确

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

预期: PR URL 输出

- [ ] **Step 4: 报告 PR URL 给用户**

输出示例: `🔗 https://github.com/oneMuggle/sage/pull/185`

---

## Self-Review Checklist

完成实施后逐项验证:

- [ ] `docs/plans/` 只剩 2 个文件(`ls docs/plans/` 输出)
- [ ] `docs/superpowers/plans/` 为空目录(`ls -A docs/superpowers/plans/` 空)
- [ ] `docs/superpowers/specs/README.md` 存在(`ls docs/superpowers/specs/README.md`)
- [ ] `docs/technical/` 无编号重号(`ls docs/technical/ | awk '{print $1}' | cut -d- -f1 | sort | uniq -d` 空)
- [ ] `docs/technical/31-win7-lts.md` 存在
- [ ] `docs/technical/24-skills-system.md` 含"定时任务"小节
- [ ] `docs/README.md` 含"子目录总览"小节
- [ ] 失效链接 grep 命令返回空
- [ ] git log 有 7 个原子 commit
- [ ] PR 创建成功

---

_本实施计划基于 spec `docs/superpowers/specs/2026-07-17-docs-cleanup-design.md`,通过 superpowers:writing-plans 流程产生。_