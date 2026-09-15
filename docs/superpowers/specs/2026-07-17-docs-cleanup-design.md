# Sage 文档整理 (Docs Cleanup) — 设计 Spec

**日期**: 2026-07-17
**作者**: Claude (via superpowers:brainstorming)
**状态**: 待用户批准
**范围**: `docs/` 整目录(激进方案)

---

## 1. 背景与目标

### 1.1 背景

Sage 项目的 `docs/` 目录经过 2 个月的密集开发(M3-M9, Office features, Win7 sync 等),积累了大量文档。当前状态偏离 `feature-development.md`(项目根)的硬约束:

> **plans 目录 (`docs/plans/`) 仅保留进行中/未完成的计划文档**
> 功能实现后,将功能点并入技术手册/用户手册对应章节,并入后**直接删除**计划文件,不归档、不保留历史版本

### 1.2 目标

让 `docs/` 重新对齐项目文档规范:
1. `docs/plans/` 只留进行中的实施计划(2 个)
2. `docs/superpowers/plans/` 删除(全 21 个历史执行计划)
3. `docs/superpowers/specs/` 保留 + 新增 README(明确归档定位)
4. `docs/technical/` 修复编号冲突(21×2、24×2)
5. `docs/README.md` 新增"子目录总览"段落
6. 失效链接审计与修复

### 1.3 非目标

- ❌ 不拆分 `25-llm-wiki-integration.md`(934 行)等巨型文件
- ❌ 不重写 `docs/01-14.md` 核心章节的过时内容
- ❌ 不动 `docs/philosophy/`、`docs/verification/`、`docs/superpowers/ideas/`
- ❌ 不同步 `release/win7` 分支(由后续 cherry-pick 处理)

---

## 2. 设计原则

| 原则 | 体现 |
|---|---|
| **KISS** | 不拆分巨型文件,仅做"必删 + 必改 + 必加" |
| **DRY** | 删除前 grep 引用,确保无悬空 |
| **YAGNI** | 不为"未来可能想看"留历史档案——git 历史永久存档 |
| **规则对齐** | 严格按 `feature-development.md` 与项目"过时文档立即删除"约束 |
| **可回滚** | 每类变更独立 commit,出问题 `git revert <hash>` 即可 |

---

## 3. 设计决策汇总

### 3.1 已确认的策略选择

| 决策点 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 整理范围 | 保守/中等/激进 | **激进(全 docs/)** | 用户指定 |
| `superpowers/` 处理 | 全删/留 plans/留 specs/全留 | **删 plans/(21),留 specs/(13)+加 README** | plans 是已执行的实施计划,git 已存档;specs 是设计思考,有参考价值 |
| `docs/plans/` 删除判定 | 严格按状态/git 交叉/双验证 | **git 交叉验证** | 更准确,反映"实际是否完成"而非"自我标记" |
| 三个候选方案 | A 安全/B 中等/C 激进 | **B(中等清理)** | 在"必删/必改"基础上加 merge/索引收益,避免 C 的引用破坏代价 |

### 3.2 不采用的方案

- **方案 A(机械最小化)**: 留下 `24-scheduled-tasks.md` 单独小文件,与 `24-skills-system.md` 595 行规模严重不匹配。
- **方案 C(激进重整)**: 拆分巨型文件会破坏 commit message、PR description、其他文档里的链接,得不偿失。

---

## 4. 具体改动清单

### 4.1 `docs/plans/` — 删除 26 个,保留 2 个

#### 删除(共 26 个)

| # | 文件 | 判定依据 |
|---|---|---|
| 1 | `2026-05-17-ai-agent-desktop-client.md` | 状态"实施中"但所有模块(W7/三层记忆/多 Agent)已通过 PR #41, #57, #67 等 merge |
| 2 | `2026-05-28_ui-integration-css-variables.md` | Prettier + CSS 变量工作已落地(9137705 等) |
| 3 | `2026-05-29_sage-core-features.md` | 状态"阶段 1-4 已完成",内容已并入核心章节 |
| 4 | `2026-05-30_llm-wiki.md` | 状态"实施中"但 wiki 全套已通过 PR #5-#12 merge |
| 5 | `2026-06-01_sage-core-llm-conversation-foundation.md` | LLM 对话基础已通过 PR #57 落地 |
| 6 | `2026-06-01_sage-next-features.md` | 状态明确"2026-06-04 完成" |
| 7 | `2026-06-12_llm-wiki-llm-integration.md` | 状态"计划中"但 PR-8 Phase 1-8 已 merge (PR #5-#12) |
| 8 | `2026-06-17_llm-thinking-display.md` | 思考显示已通过 PR #63 落地 |
| 9 | `2026-06-18_drawio-integration.md` | 状态明确"✅ 已完成" |
| 10 | `2026-06-19_ai-agent-memory-research.md` | 研究性,内容已融入 `docs/04-memory.md` |
| 11 | `2026-06-19_enhancement-plans-overview.md` | 总览,所有子计划各自有归宿 |
| 12 | `2026-06-19_formal-verification-maps.md` | 验证 map 已落地为 `docs/verification/g001-g009` |
| 13 | `2026-06-19_mcp-lifecycle-management.md` | MCP 功能已落地 |
| 14 | `2026-06-19_memory-integration-to-chatservice.md` | 已通过 PR #41 等落地 |
| 15 | `2026-06-19_memory-optimization-plan.md` | 状态"方案设计中",纯设计阶段,内容已融入核心章节 |
| 16 | `2026-06-19_multi-agent-coordination.md` | 已通过 PR #41 落地 |
| 17 | `2026-06-19_parity-alignment.md` | 双轨策略已落地为 `docs/technical/21-win7-lts.md` 等 |
| 18 | `2026-06-19_philosophy-document.md` | 哲学已落地为 `docs/philosophy/*.md` |
| 19 | `2026-06-19_rag-service-extraction.md` | RAG 已融入 `docs/technical/25-llm-wiki-integration.md` |
| 20 | `2026-06-19_shared-core-library.md` | shared-core 概念已并入 `docs/02-architecture.md` 等 |
| 21 | `2026-06-19_verification-map-system.md` | 已落地为 `docs/verification/g001-g009` + TEMPLATE |
| 22 | `2026-06-22_agent-orchestrator-wiring.md` | 状态"✅ 完成 (4 阶段全部 GREEN)" |
| 23 | `2026-06-23_optimization-plan-aionui-reference.md` | 已通过 PR #74 等落地 |
| 24 | `2026-06-26_llm-wiki-optimization.md` | 状态"已完成" |
| 25 | `2026-06-26_multi-agent-optimization-from-claw-code.md` | 已通过 PR #67 落地 |
| 26 | `2026-06-26_officecli-integration.md` | 实际工作由 PR #183/#184 (office features) 替代 |

#### 保留(共 2 个)

| 文件 | 保留理由 |
|---|---|
| `2026-07-04_chat-tool-path-hardening-from-claw-code.md` | spawn ENOENT 修复链(PR #130)刚合并,Phase 2/3 仍有后续工作 |
| `2026-07-16_office-features.md` | 状态明确"进行中",Phase 1 已合并(PR #183+#184),Phase 2/3 待实施 |

### 4.2 `docs/superpowers/plans/` — 全删(21 个)

21 个文件均为已合并实施计划,信息已通过 git commit message + PR 完整保留。

唯一例外检查:2026-07-10 `release-branch-strategy-plan.md` 对应 PR #129 已 merged,故也在删除之列。

### 4.3 `docs/superpowers/specs/` — 保留 + 新增 README

#### 保留理由

13 个 spec 是"设计思考记录",即使对应功能已实现,设计阶段的取舍/方案讨论仍有参考价值(尤其对比实现后的偏差)。

#### 新增 `docs/superpowers/specs/README.md`

内容:
- 目录定位:"Sage 各功能/阶段的**设计 spec 归档**。功能实施后,spec 保留作为'设计 vs 实际'对比基线"
- 归档策略:"功能实现后,spec 不删除;新功能实现后对应章节并入 `docs/technical/` 或 `docs/user-manual/` 主目录"
- 章节目录(13 个 spec 列表,一句话简介,日期)
- 与其他目录关系:`docs/plans/`(执行计划)、`docs/technical/`(已归档技术文档)、`docs/superpowers/ideas/`(未来想法)

### 4.4 `docs/technical/` — 编号冲突修复

#### 冲突 1:`21-llm-proxy.md` vs `21-win7-lts.md`

| 文件 | 行数 | 提交日期 | 处置 |
|---|---|---|---|
| `21-llm-proxy.md` | 324 | 2026-06-26 | **保留原名(不动)** |
| `21-win7-lts.md` | 193 | 2026-07-07 | **`git mv` 为 `31-win7-lts.md`** |

理由:31 是 30(最新)之后的第一个空闲号,挪到末尾避免再冲突。`21-llm-proxy.md` 因是更早的文档,保持其位置不变以最小化引用破坏。

同步更新:
- `docs/technical/README.md` 表格条目改 31
- 其他文件里指向 `21-win7-lts.md` 的链接改为 `31-win7-lts.md`

#### 冲突 2:`24-scheduled-tasks.md` vs `24-skills-system.md`

| 文件 | 行数 | 处置 |
|---|---|---|
| `24-scheduled-tasks.md` | 56 | **内容并入 `24-skills-system.md` §"定时任务"小节,删除本文件**。合并位置:在"§SKILL.md v2 适配层"或"§Slash Command"附近最合理(实施时确定) |
| `24-skills-system.md` | 595 | 保留,新增定时任务小节 |

理由:`24-scheduled-tasks.md` 是设计 sketch,内容已被 `24-skills-system.md` 的"gating/scripts/dispatch"等涵盖。

### 4.5 `docs/README.md` — 新增"子目录总览"

在"技术专题"小节后、"核心技术参考"前,新增段落:

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

### 4.6 失效链接审计

#### 审计范围

`docs/**/*.md` + 根 `*.md`(排除 `node_modules/`, `dist/`)

#### 审计命令

```bash
grep -rEn "\(.*\.md\)" docs/ --include="*.md" | \
  grep -E "(2026-05-(17|28|29|30)|2026-06-(01|12|17|18|19|22|23|26)|24-scheduled-tasks|21-win7-lts)\.md"
```

#### 修复策略

- 指向已删 plan 的链接 → 删除该行或该段;若该 plan 全部内容已并入其他章节,直接删除链接行
- 指向 `24-scheduled-tasks.md` 的链接 → 改为 `24-skills-system.md#定时任务`
- 指向 `21-win7-lts.md` 的链接 → 改为 `31-win7-lts.md`

---

## 5. 实施计划(7 步提交)

| # | 步骤 | 动作 | 验证 |
|---|---|---|---|
| 1 | 创建分支 | `git switch -c chore/docs-cleanup-2026-07` | `git branch` 列出 |
| 2 | 删除 docs/plans/ 26 文件 | `git rm` × 26 | `ls docs/plans/` 应剩 2 个 |
| 3 | 删除 docs/superpowers/plans/ 21 文件 | `git rm` × 21 | `ls docs/superpowers/plans/` 应空 |
| 4 | technical/24-scheduled-tasks.md 内容并入 24-skills-system.md | Edit + `git rm` | 24-skills-system.md 行数增加 |
| 5 | technical/21-win7-lts.md → 31-win7-lts.md | `git mv` + README.md 更新 + grep 失效链接 | `ls docs/technical/` 编号无重号 |
| 6 | 新增 docs/superpowers/specs/README.md | Write | 文件存在且结构完整 |
| 7 | 新增 docs/README.md "子目录总览"小节 | Edit | 内容出现在 docs/README.md 中 |
| 8 | 失效链接审计与修复 | grep + Edit 多文件 | grep 命令应返回空 |
| 9 | 提交 | `git commit -m "chore(docs): ..."` 1 个 commit | git log 显示 |

注:步骤 2-8 各为 1 个独立 commit(共 7 个),便于回滚。

### 5.1 PR 流程

- 推送 `chore/docs-cleanup-2026-07` 到 origin
- 创建 PR(标题:`chore(docs): 整理 docs 目录 - 删除过期计划 + 修复编号冲突`)
- CI 应自然过(纯文档变更)
- 等 CI 绿 + AI review → 用户 merge

---

## 6. 风险评估

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 误删仍需引用的 plan | 中 | 删前 grep 引用点,有引用保留 |
| 24-scheduled-tasks 合并漏内容 | 中 | 合并前 Read 两个文件,合并后 diff |
| 编号改动漏改 README | 中 | 步骤 5 内 explicit 包含 README 更新 |
| 跨分支影响(win7) | 低 | 仅动 main,win7 由后续 cherry-pick |
| 巨型文件不拆 → 未来维护难 | 低 | 暂可接受,出现"维护痛点"再启新 spec |

---

## 7. 验证清单

完成后所有项应为 ✅:

- [ ] `docs/plans/` 只剩 2 个文件(2026-07-04, 2026-07-16)
- [ ] `docs/superpowers/plans/` 为空目录(或保留为 .gitkeep)
- [ ] `docs/superpowers/specs/README.md` 存在,含 13 个 spec 索引
- [ ] `docs/technical/` 无编号重号(21 唯一、24 唯一)
- [ ] `docs/technical/31-win7-lts.md` 存在,内容与原 21-win7-lts 一致
- [ ] `docs/technical/24-skills-system.md` 含定时任务小节
- [ ] `docs/README.md` 含"子目录总览"小节
- [ ] grep 失效链接命令返回空
- [ ] git log 有 7 个原子 commit

---

## 8. 后续(非本次范围)

- `release/win7` 是否需同步清理? —— 另起 cherry-pick PR
- `docs/01-14.md` 核心章节陈旧引用审计 —— 后续内容 review PR
- 巨型文件拆分(25-llm-wiki-integration.md 等)—— 出现维护痛点时启新 spec
- `docs/philosophy/` `docs/verification/` 内容审计 —— 后续 review

---

_本 spec 通过 superpowers:brainstorming 流程产生,已获用户在 6 个设计节点上的逐节批准。_