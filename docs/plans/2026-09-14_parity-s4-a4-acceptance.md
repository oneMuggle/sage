# 对标 Sprint 2（parity-s4）A4——自动验收闭环（交付包）

> 日期: 2026-09-14 · 基线: origin/main `fb6f25c5`（A1 `746a66bb` 已合入分支）
> 分支: `feat/parity-s4` · worktree: `.worktrees/feat-parity-s4`
> 上游方案: 《Sage优化建议方案》主题 A（Agent 工作台）之 A4
> 定义原文: 任务完成自动跑"测试 + lint + reviewer 评审"，产物（diff/artifact/Office）
> 一次性呈现为"交付包"，用户一键接受/打回。

## 1. 侦察结论（现状盘点）

### 1.1 reviewer 评审：后端闭环已有，前端只通了一半

- 后端 `backend/orchestration/review.py`：reviewer 子 agent 复核聚合结果 →
  assertions → verdict（pass/fail）→ `ReviewReport` + `lane.review.submitted` 事件。
- 前端可见性：verdict 经聊天 NDJSON 流 → `taskBoard.review` →
  `TaskTreeSection` 显示"复核通过 / 存在疑问"（`useChat.test.ts:1471` 有覆盖）。
- **缺口**：`LaneEventType` 无 `review.submitted`，lane 通道收不到评审结论；
  离开会话页即看不到 verdict（A4 要修的正是这个）。

### 1.2 测试 + lint 自动跑：无产品化设施，有积木

- 后端无 pytest/vitest runner；ruff 只是仓库自用 lint。
- 可复用积木：`bash_tool`（shell 执行）、`git_tool`、`office_lint_tool`
  （Office 文档 lint，已有）、`execute_code_tool`。
- lane 自带 `worktree` 字段（`types.ts:913`）：编码任务 checks 可定 `cwd=worktree` 跑。

### 1.3 交付包呈现：有零件，无整车

- `SplitDiff`（unified diff 渲染，`testid=split-diff`）+ `ChangesSection`
  （支持 revert hunks）+ `ArtifactViewer/ArtifactsSection` +
  `OfficePreviewPanel`（Office 富预览）。无"交付包"聚合视图。

### 1.4 触发点：齐全

- lane：`laneBoardStore.applyEvent`（`lane.succeeded`）/
  `applyCanonicalEvent`（`task.succeeded/completed`）；
- office：`OfficeGenerateForm` 两 finally（成功/失败都调 `finishTask`）、
  `OfficePreviewPanel`（export）；
- wiki：`useWikiIngest.broadcast` 的 completed 分支。
- 调用机制：前端 `invoke` → preload → 后端 HTTP `/api/v1/*`；
  新数据需求 = 新 channel + route，或复用 `listLaneEvents` + 新事件类型。

### 1.5 merge-back 现状：零基础（用户要求本批做接受=merge，关键约束）

- worktree 是 **detached 空分支**（`git worktree add --detach <dest> HEAD`），
  模块 docstring 明确声明"只提供隔离，不自动合并产物回主工作区"。
- `_run_subagent` 的 `finally` **直接删除 worktree**：验收时 `lane.worktree`
  已是悬空路径——必须加留存策略（保留至接受/打回）。
- 只有 chat 派发 lane 带 worktree；API-lane（M5/B2、router、agent_tool）
  `worktree=None`（变更直接落工作区，无物可合，接受=归档）。

### 1.6 Office lint：路由有，前端无

- 后端 `POST /word/lint` 已存在（`WordLintRequest`→`WordLintResult`：
  ok/issue/error/warning 计数 + issues 明细，`models.py:1268`）。
- 前端 `src/features/office` 零 lint 调用——需新增 `officeApi.lintWord` +
  invoke channel。

## 2. 方案

### 2.1 合批交付（用户 2026-09-14 确认）：编码 + Office 同批，wiki 不做

- **A4a 编码任务交付包**：lane checks + reviewer 透出 + diff + 接受（merge）/打回。
- **A4b Office 交付包（同批）**：generate 成功后调 `/word/lint` +
  预览 + 接受（归档）/打回（跳 Office 页）。
- **wiki**：不做（ingest 产物是索引数据，无用户可验收的 diff/文档；
  ingest 失败已有 error 展示位）。
- 落地顺序：后端 acceptance+merge → 前端 lane 交付包 → 前端 Office
  交付包；i18n 与测试随各段走，commits 按段拆分。

### 2.2 后端：acceptance checks + worktree 留存/merge-back + 事件透出

- 新模块 `backend/orchestration/acceptance.py`：lane 进入 `succeeded`
  后自动跑 checks，`cwd=lane.worktree`（无 worktree 的 API-lane 就地跑
  workspace，此段记 skip；超时熔断，subprocess 直调——同 worktree.py
  先例，不走 tool 审批栈，防自检触发审批递归；命令白名单 + 无 shell）：
  - 恒跑：`git diff --stat`（产物摘要；非 git 目录记 skip）；
  - 自动探测（用户确认，白名单制）：`pytest.ini`/`pyproject[tool.pytest]`
    → `pytest -q`；`package.json` + tsconfig → `npx tsc --noEmit`；
    探测表之外不执行任何命令；
  - 显式配置优先：lane `metadata.acceptance_checks` 非空则跑配置命令
    （用户/模板可配，条数上限 5，超时熔断）；
  - 结果记新 lane 事件 `lane.acceptance.completed`，
    `metadata = { checks: [{name, passed, summary}], all_passed }`。
- worktree 留存 + merge-back（"接受=merge"，用户确认；§1.5 约束下的新语义）：
  - 留存：succeeded 且带 worktree 的 lane 跳过 finally 清理，保留至
    接受/打回（`metadata.acceptance_pending=true`；打回/接受后清理；
    崩溃残留沿用 `_sweep_stale_worktrees` 机会清扫 + 新增过期兜底）；
  - 接受 merge：新后端动作（建议 `POST .../lanes/{id}/accept`）：
    worktree 内建分支 `lane/<run>/<task>`（add -A + commit，
    记录 base HEAD 备审计）→ 主工作区 `merge --no-ff` →
    成功记 `lane.accepted` 事件 + `remove_worktree_async`；
  - 拒绝条件（fail-closed）：主工作区脏（有未提交变更）→ 拒绝并提示
    先提交；merge 冲突 → abort + 返回冲突文件列表，lane 保持待验收，
    用户手动解决后可重试；worktree 已丢失 → 报错并降级为纯归档。
- reviewer 结论透出：`lane.review.submitted` 事件已存在，
  确认其 payload 含 verdict/assertion_count 并可被 `listLaneEvents` 取到
  （如事件未落库则补落库，不改评审逻辑本身）。
- 不做：checks 失败自动修复/重跑（A2 范畴）。

### 2.3 前端：交付包抽屉（lane + Office）+ 任务中心接入

- 新组件 `DeliveryPackageDrawer`（`src/widgets/task-center/`），lane 段：
  - 头部：任务名 + 综合状态（checks 全过 + reviewer pass = 可验收）；
  - 三段：① 自动检查（checks 列表：名/过/摘要）；② 复核结论
    （verdict + assertion_count + 跳会话看 reviewer block）；
    ③ 产物 diff（`SplitDiff` 复用，diff 文本经 `listLaneEvents` 或新
    channel 取；超长截断，截断提示复用 ChangesSection 模式）；
  - 底部：一键**接受**（调 accept → merge，冲突/脏工作区按后端返回
    展示）/ **打回**。
- Office 段（同批）：generate 成功后前端调新增 `officeApi.lintWord`
  （新 invoke channel → 已有 `POST /word/lint`）→ 交付包展示 lint
  结果（ok/error/warning 计数 + issues 列表 Top N）+ `OfficePreviewPanel`
  嵌入预览；接受=归档（`completeTask`），打回=跳 Office 页定位文档。
- 任务中心接入（A1 状态机天然对齐）：
  - lane succeeded + acceptance 就绪 / office lint 完成 → 对应条目切
    `awaiting_approval`（A1 已有"待审批"徽章、过滤与跳转位）；
  - 点击条目 → 打开交付包抽屉（替代直跳；原跳转入口保留在抽屉内）。
- 接受/打回语义（用户确认）：
  - lane **接受** = 后端 merge worktree（§2.2）→ 成功归档 + toast；
    冲突/脏工作区/丢失按后端返回展示，不静默；
  - lane **打回** = 跳回绑定会话并预填 followup 草稿（"验收打回：<问题>"，
    复用页内重发链路）+ 后端清理保留的 worktree；
  - 无 worktree 的 API-lane：接受=归档（无物可合，抽屉内明示
    "变更已直接落在工作区"）。

### 2.4 i18n

- `delivery.*` 约 20 个 key（lane + office 两段：标题/检查/复核/
  产物/接受/打回/冲突/截断提示等），中英齐。

## 3. 不做的事

- checks 失败自修复/重跑（A2 范畴）；
- wiki 验收；
- 后端评审逻辑改动（只透出，不改 verdict 算法）；
- merge 冲突自动解决（只 abort + 列冲突文件，用户手动解）；
- 新依赖；新 channel 控制在 2 个以内（accept + lint，优先复用既有路由面）。

## 4. 测试

- 后端 pytest：checks（diff 摘要恒过/skip、探测表命中、配置优先、
  超时熔断、事件落库）；merge-back（留存跳过清理、commit+merge 成功、
  脏工作区拒绝、冲突 abort + 冲突列表、worktree 丢失降级）；
  reviewer 事件落库含 verdict；
- 前端：抽屉 lane 三段 + office 两段（lint/预览）渲染、接受调 accept
  （成功归档/冲突展示）、打回跳转预填 + 清理、条目 awaiting_approval
  切抽屉、无 worktree lane 明示；
- 回归：`tsc --noEmit` + lane/orchestration/task-center/office suites +
  后端相关单测。

## 5. win7 对齐

- 前端：常规 React/Zustand，无新语法；
- 后端：`acceptance.py` 纯标准库 + 既有 tool 调用，注意 `release/win7`
  的 Python 3.8 兼容（`typing` 注解风格同 backend 现状）；
- 新功能按 `31-win7-lts.md` §2 不进 `release/win7`，本批默认 main only。

## 6. 用户确认记录（2026-09-14）

1. 分批：**A4a + Office 同批**，wiki 不做。
2. 接受语义：**本批就要 worktree merge**（§2.2 fail-closed 设计）。
3. checks：**自动探测**（白名单探测表 + 显式配置优先）。
