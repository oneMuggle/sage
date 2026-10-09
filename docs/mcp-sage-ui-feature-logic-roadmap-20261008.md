# Sage 项目优化建议方案（UI / 功能 / 逻辑）— 2026-10-08 合入后新基线

> **基线**：`origin/main` @ `e59a6befc`、`origin/release/win7` @ `3ce308d56`（2026-10-08 完成 `#1891`、`#1892`、`#1898`、`#1899`、`#1900`、`#1901`、`#1902`、`#1903`、`#1904`、`#1906`、`#1907`、`#1908` 合入及 `#1890`/`#1893`–`#1896` 收口之后）。
> **定位**：基于今日 12 个 PR 合入后的最新代码现场，剔除已落地项，聚焦**刚被解阻的架构收口项**与**下一阶段最高投资回报率（ROI）的改进项**，从 **UI（视觉与交互）**、**功能（产品价值闭环）**、**逻辑（契约、数据与架构治理）** 三个维度给出可分批执行的落地方案。

---

## 0. 已收口基线与本轮优先级总览

### 0.1 今日已落地基线（不再重复立项）

| 领域 | 已合入能力 | 对应 PR / 提交 |
| --- | --- | --- |
| **逻辑 / IPC 契约** | `export-ipc-manifest.mjs` + T1/T2/T3 契约测试 + 恢复 Office/Projects/Prompts 25 条断链 + 18 条 UI$
ightarrow$Bridge$
ightarrow$HTTP 线路测试 | `main` `#1899` (`a618367ba`) / `win7` `#1897` (`18bcc2805`) |
| **逻辑 / 架构棘轮** | `architecture-check.mjs --tighten / --max-slack` 落地，`main` 72 项基线松弛清零 | `main` `#1891` (`e59a6befc`) |
| **功能 / 产品路线 A&B** | 可信底座（严格保存回执、协议感知状态、长期记忆契约）+ 成果导向首页、项目工作台、Office 交付抽屉初版 | `main` `#1867` (`48635ffcf`) / `win7` `#1868` (`4a745ed43`) |
| **UI / 侧栏与轨迹一期** | 左栏 56px 常驻 rail + 单滚动容器 + `PanelShell`/`panelRegistry` 地基；右栏新增 `TrajectoryPane`（F3 一期） | `main` `#1870`/`#1873`/`#1828` (`4e77d8714`) / `win7` `#1872`/`#1874`/`#1908` (`a92a875c6`) |
| **逻辑 / 路由与仓储单测** | R78 Zotero 路由单测 18 例；R185 `TaskRepository.get_ready_tasks` 跨状态依赖判定修复 + 编排/Agent 仓储单测 30 例 | `main` `#1900` (`ef373c879`), `#1906` (`4d85650cc`) / `win7` `#1901` (`f69c4893f`), `#1907` (`3ce308d56`) |

### 0.2 下一阶段建议方案速览（按优先级排序）

| 编号 | 维度 | 建议项 | 优先级 | 预计工期 | 当前状态 / 解阻条件 |
| --- | --- | --- | --- | --- | --- |
| **U1** | UI | 右栏与底栏统一槽位收口（UX-IA R3 批次 C：三套右栏迁 `PanelShell` + 头部瘦身 + `TaskCenter` 退让） | **P0** | 1.5–2 天 | **今日 `#1828` 合入后已正式解阻** |
| **F1** | 功能 | 对话产物（Artifact）携带 `workspace_path`/`format_spec` 直通 `OfficeDeliveryDrawer` 验收闭环 | **P0** | 2–3 天 | 前置 `#1209`/`#1867` 已合入，可立即开工 |
| **L1** | 逻辑 | `electron/commands.ts`（1,385 行）按域彻底拆分至 `electron/commandRoutes/*.ts` 并退出架构基线 | **P0** | 1 天 | `#1899` 已搭好分域骨架与 T3 门禁 |
| **U2** | UI | 左栏「项目 $
ightarrow$ 会话」合并树（UX-IA R3 批次 B-2） | **P1** | 1.5 天 | **今日 `#1867` 合入后已正式解阻** |
| **U3** | UI | 字号标尺落地（`text-[Npx]` 238 处棘轮 + `text-ui-2xs` 扩展 + 分目录 codemod） | **P1** | 2 天 | 规范已定，防新代码继续绕过 `--ui-font-size` |
| **U4** | UI | 用户操作失败可见性规范（统一 `reportActionFailure`，清理 UI 静默回滚/静默隐藏） | **P1** | 1 天 | 与 L3 联动 |
| **F2** | 功能 | Office 文档版本一致性与 `office_apply` 409 冲突保护（收口在飞 `#1626`） | **P1** | 0.5–1 天 | `.worktrees/fix/t14-1626` 已有实现，需 rebase |
| **F3** | 功能 | 清零最后 2 条 IPC 已知缺口（`#1010` `projects_update_allowed_paths` + `wiki_chat_cancel`） | **P1** | 0.5–1 天 | `electron/ipc-known-gaps.json` 2 $
ightarrow$ 0 |
| **F4** | 功能 | 模型轨迹查看器（`TrajectoryPane`）二期：对接后端事件源，补齐耗时/Token/子代理遥测 | **P1** | 2 天 | 一期纯前端已落地（`#1828`/`#1908`） |
| **L2** | 逻辑 | 数据仓储层（`backend/data/*_repo.py`）单测补齐（剩余 16 个仓储模块，R185 续篇） | **P1** | 3–4 天（分批） | R185 已验证高缺陷检出率 |
| **L3** | 逻辑 | 后端 349 处 `except Exception` 吞异常分级治理 + Ruff `BLE001`/`S110` 棘轮 | **P1** | 持续（首批 1 天） | 先治核心调度与工具链路 |
| **L4** | 逻辑 | 双轨防漂移门禁：`main` 前置运行 `check_py38_compat.py` + `release/win7` 基线 `--tighten` | **P1** | 0.5 天 | 根治 win7 摘樱桃 PEP 604 地雷 |
| **U5** | UI | `eslint-plugin-jsx-a11y` 门禁 + `i18n/{en,zh}.ts`（1,322/1,289 行）按域拆分 | **P2** | 1.5 天 | 降低大文件冲突面 |
| **F5** | 功能 | 产品路线批次 C 续篇：定时任务技能引用校验 UI + 单任务后端硬预算拦截 | **P2** | 2–3 天 | 见 `2026-10-01_sage-product-roadmap-batchC.md` |
| **L5** | 逻辑 | `hex_routes` / `legacy_routes` 5 组重复路由收敛 + `office_routes.py`（1,459 行）子路由拆分 | **P2** | 2 天 | 配合 DSH 路线推进 |

---

## 一、UI 维度建议方案（视觉层级、交互一致性与可访问性）

### U1 · 右栏与底栏统一槽位收口（UX-IA R3 批次 C，P0）

- **现状与痛点（已核实行号）**：
  - `src/features/app-panels/panelRegistry.ts:116-152`、`src/features/app-panels/usePanelStore.ts`（统一键 `sage:panels:v1`）与 `src/shared/ui/PanelShell.tsx` 已在 `#1870` 落地，但因等待 `#1828` 合入，面板本体尚未迁移。
  - 今日 `#1828` 合入后，`src/widgets/chat/RightPanel.tsx:56-79` 已扩展至 **6 个 Tab**（`progress` / `outline` / `trajectory` / `changes` / `preview` / `artifacts`），外加铃铛 `AutoOpenToggle`（`:100-119`）、`S/M/L` 三档宽度按钮（`text-[10px]`，点击热区仅 20px）、最大化与关闭按钮挤在同一行头部，窄宽度（320px）下严重拥挤。
  - `src/widgets/wiki/RightPanel.tsx` 与 `src/pages/ModelCatalog.tsx` 仍维护各自独立的右栏实现；`src/widgets/task-center/TaskCenterWidget.tsx:305` 以 `fixed bottom-4 right-4 z-40` 常驻浮层压在右栏右下角，右栏最大化时仍不退让。
- **落地方案**：
  1. **三套右栏迁入 `PanelShell`**：将 `src/widgets/chat/RightPanel.tsx`、`src/widgets/wiki/RightPanel.tsx`、`src/pages/ModelCatalog.tsx` 统一接入 `usePanelStore` 的 `right` 槽位，`src/widgets/chat/TerminalPanel.tsx` 接入 `bottom` 槽位。
  2. **头部减负与热区达标**：保留 6 个一级 Tab 切换；将 `AutoOpenToggle`、`S/M/L` 宽度档位、最大化收进右栏头部右侧的 `⋯` 视图菜单，所有图标按钮点击热区统一 $\ge 28	ext{px}$（满足 `DESIGN.md` §4）。
  3. **浮层互斥退让**：`TaskCenterWidget.tsx:305` 订阅 `usePanelStore` 的最大化状态，当 `right` 或 `bottom` 槽位处于 `maximized: true` 时自动折叠为底栏徽标或隐藏浮层。
- **验收标准**：`npx vitest run src/widgets/chat src/features/app-panels` 全绿；右栏最大化时无 `z-40` 浮层遮挡；旧 localStorage 键迁移至 `sage:panels:v1` 无状态丢失。

### U2 · 左栏「项目 $
ightarrow$ 会话」合并树（UX-IA R3 批次 B-2，P1）

- **现状与痛点**：
  - `#1873` 完成了左栏 56px 常驻图标 rail + 单滚动内容列，但内容列内 `src/widgets/sidebar/sections/ProjectSection.tsx` 与 `src/widgets/sidebar/sections/ConversationsSection.tsx` 仍上下分立。用户在项目内工作时，需要在上方项目区与下方会话列表之间来回定位。
- **落地方案**：
  - 在 `left-list` 槽位将「项目」与「会话」收敛为统一的树形列表：项目行可展开其名下会话（调用 `projects_list_sessions`），行尾 `+` 按钮直接调用 `#1899` 已修复的 `projects_create_session`（`POST /api/v1/projects/{id}/sessions`）在当前项目下新建对话；未归属项目的会话归入底部「独立对话」分组。

### U3 · 字号标尺落地与 ESLint 棘轮（`text-[Npx]` 238 处治理，P1）

- **现状与痛点**：
  - `tailwind.config.js:93-98` 定义了由用户字号设置 `--ui-font-size` 动态驱动的 `text-ui-*` 标尺，但当前 `src/` 非测试代码中仍有 **238 处**硬编码 `text-[Npx]`（相比 10-02 扫描时的 231 处又新增了 7 处），主要集中在 `src/widgets/sidebar/sections/ProjectSection.tsx`（20 处）、`src/widgets/chat/Message.tsx`（16 处）、`src/widgets/chat/progress/TaskTreeSection.tsx`（13 处）、`src/widgets/chat/ContextMeter.tsx`（11 处）。
  - 这 238 处文本全部使用固定像素（10px/11px 为主），用户在设置页调大字号时完全不缩放。
- **落地方案**：
  1. **先上 ESLint 棘轮**：在 `eslint.config.js` 中增加针对 `text-[*px]` 的扫描脚本或规则（类似 `architecture-baseline.json`，以当前 **238 处**为硬上限，只降不增）。
  2. **补齐紧凑档位并分批替换**：在 `tailwind.config.js` 中新增 `text-ui-2xs: calc(var(--ui-font-size, 14px) - 3px)`（默认 11px，随用户字号等比缩放），保持现有高信息密度视觉不变；将快捷键徽标统一为 `text-ui-xs`，其余元信息分目录替换为 `text-ui-2xs` / `text-ui-sm`。

### U4 · 用户操作失败可见性规范（`reportActionFailure`，P1）

- **现状与痛点**：
  - 前端 `src/features/` 与 `src/widgets/` 中存在 116 处吞异常点，典型反模式包括：
    - **静默回滚**：`src/pages/settings/PromptTemplatesTab.tsx:63-66` 拖拽排序失败时 `catch { await load() }`，条目弹回原位但无任何错误提示；
    - **静默隐藏**：`src/features/office/OfficeCapabilityBar.tsx:54-60` 后端能力探测失败时直接返回 `null` 隐藏整条能力栏，用户无从得知为何功能消失。
- **落地方案**：
  - 新增 `src/shared/lib/reportActionFailure.ts`（封装 `toast.error` + `logger.warn` + 标准错误摘要提取），将全部用户主动触发的写操作（A 类）catch 块接入显式反馈；将 `OfficeCapabilityBar` 探测失败改为展示「部分转换能力未就绪（原因）」弱提示条。

### U5 · 无障碍 ESLint 门禁与 `i18n/{en,zh}.ts` 按域拆分（P2）

- **现状与痛点**：
  - `src/shared/lib/i18n/en.ts`（1,322 行）与 `src/shared/lib/i18n/zh.ts`（1,289 行）均已超过 1,250 行，每个功能 PR 追加文案都会触发同一文件尾部的合并冲突（今日在 `main` 与 `release/win7` 均出现了 i18n 基线与合并冲突）。
- **落地方案**：
  - 将 `en.ts` / `zh.ts` 拆分为 `src/shared/lib/i18n/locales/{en,zh}/{common,chat,office,projects,settings,wiki}.ts`，由 `en.ts` / `zh.ts` 做聚合导出（各 $<50$ 行），并将其从 `architecture-baseline.json` 中移除；同时引入 `eslint-plugin-jsx-a11y` 守护纯图标按钮的 `aria-label`。

---

## 二、功能维度建议方案（打通核心产品价值闭环）

### F1 · 对话产物（Artifact）直通 `OfficeDeliveryDrawer` 验收闭环（P0）

- **现状与痛点（已核实源码）**：
  - `backend/tools/file_tool.py:144-160` 中的 `_record_artifact_safely(resolved_path: str, size: int)` 与 `backend/data/artifact_repo.py:44-118` 中的 `Artifact` 数据类目前只存储 `(id, session_id, tool_call_id, path, name, kind, size, created_at)`。
  - 当 AI 通过 `backend/tools/office_create_tool.py:1557-1558` 生成 Word/Excel/PPT 文档时，虽然工具上下文已知 `workspace_path` 与所选公文/报告规范 `format_spec`，但落库与 `artifact_created` 事件广播时丢失了这两个字段。
  - 结果是：用户在对话气泡或右栏产物列表看到生成的 `.docx` 时，无法一键带规范打开 `src/features/office/OfficeDeliveryDrawer.tsx:1-380` 执行 `lintWord`（格式检查）与 `repairWord`（一键修复），形成「对话生成」与「交付验收」两张皮。
- **落地方案**：
  1. **数据库与仓储扩展**：在 `backend/data/database.py` 新增迁移步骤，为 `artifacts` 表追加可空列 `workspace_path TEXT` 与 `format_spec TEXT`；扩展 `backend/data/artifact_repo.py:44-118` 的 `Artifact` 与 `record_artifact()`。
  2. **工具层透传与日志提级**：`backend/tools/file_tool.py:144` 的 `_record_artifact_safely` 增加可选参数 `workspace_path`、`format_spec`，并将 `:159` 的失败日志从 `logger.debug` 提升至 `logger.warning`；在 `backend/tools/office_create_tool.py:1557` 传入真实 `workspace` 与 `format_spec`。
  3. **前端气泡与产物卡片接线**：前端产物卡片识别到 `kind in ('docx','xlsx','pptx','pdf')` 时，渲染「交付验收 / 格式检查」按钮，点击后调用 `OfficeDeliveryDrawer` 并自动带入 `path`、`workspace_path` 与 `format_spec`。

### F2 · Office 文档版本一致性与 409 冲突保护（收口 `#1626`，P1）

- **现状与痛点**：
  - 在飞 PR `#1626`（工作树 `.worktrees/fix/t14-1626`，提交 `ff179b549` + `aab07e07e`）已实现 Office 预览版本戳、`office_apply` 409 冲突/幂等校验以及按内容 revision 隔离预览缓存，但当前相对 `origin/main` 处于 `CONFLICTING` 状态。
- **落地方案**：
  - 将 `.worktrees/fix/t14-1626` rebase 至最新 `origin/main`（`e59a6befc`），将新增命令登记至 `electron/commandRoutes/office.ts` 并更新 `electron/ipc-manifest.json`，合入后同步摘樱桃至 `release/win7`。

### F3 · 清零最后 2 条 IPC 已知缺口并切换契约门禁为阻塞态（P1）

- **现状与痛点**：
  - 今日 `#1899` 合入后，`electron/ipc-known-gaps.json` 已从 27 条降至仅剩 **2 条**：
    1. `projects_update_allowed_paths`：`src/widgets/permission/ApprovalDialog.tsx:142` 审批弹窗勾选「在此项目中始终允许该目录」时调用，因缺少路由每次必报错；
    2. `wiki_chat_cancel`：`src/shared/api-client/wiki.ts:288` 调用，主进程未注册。
- **落地方案**：
  - 推进在飞 PR `#1010`（提供 `projects_update_allowed_paths`）rebase 并合入；对 `wiki_chat_cancel` 在 `electron/main.ts` 补齐流式中断处理器（或清理客户端冗余调用）；将 `electron/ipc-known-gaps.json` 的 `frontendUnregistered` 清空为 `{}`，实现 IPC 契约 **0 缺口硬门禁**。

### F4 · 模型轨迹查看器（`TrajectoryPane`）二期：后端事件源与遥测联动（P1）

- **现状与痛点**：
  - `#1828` / `#1908` 落地的 `src/widgets/chat/TrajectoryPane.tsx:1-167` 与 `src/features/chat/useConversationTrajectory.ts` 目前完全从前端内存 `messages` store 派生，刷新页面后丢失工具起止时间戳、单步耗时（`duration_ms`）、缓存命中率及后台多代理编排（Orchestration Lane）子任务轨迹。
- **落地方案**：
  - 扩展 `useConversationTrajectory` 支持按 `sessionId` 拉取 `backend/data/session_event_repo.py` 与 `backend/data/orch_events_repo.py` 的持久化事件流，在 `TrajectoryPane` 时间线节点上展示单步耗时バッジ、工具重试次数与子代理泳道归属。

### F5 · 产品路线批次 C 续篇：技能 $	imes$ 定时任务 UI 接线与单任务硬预算（P2）

- **现状与痛点**：
  - `docs/plans/2026-10-01_sage-product-roadmap-batchC.md` 中规划的 `skillLink.ts` 与 `ContextMeter.tsx` 来源四态已就位，但定时任务列表侧的「失效技能引用徽标」、「从任务配方一键预填创建定时任务」以及后端执行的「单任务 Token/金额硬预算上限」尚未收口。
- **落地方案**：
  - 完成配方列表到 `CreateTaskModal.tsx` 的预填跳转（需用户显式确认时间与启用状态，不静默后台创建）；在 `backend/orchestration/chat_dispatcher.py` 与 `agent_loop` 增加服务端单任务预算阈值熔断并回传明确终态原因。

---

## 三、逻辑与架构维度建议方案（契约、数据层单测、吞异常与双轨治理）

### L1 · `electron/commands.ts`（1,385 行）按域彻底拆分（P0）

- **现状与痛点**：
  - `electron/commands.ts` 当前为 **1,385 行**（基线 1,385，零余量），历史上 `#857` 误删 13 条 IPC 路由以及多个 PR 反复冲突的根因，都是所有域共享这一个超大映射文件。
  - `#1899` 已成功建立 `electron/commandRoutes/index.ts:1-25`（已拆出 `office.ts`、`projects.ts`、`prompts.ts`）以及防重复键门禁 `T3`（`electron/__tests__/ipc-contract.test.ts`）。
- **落地方案**：
  - 将 `electron/commands.ts` 中剩余约 1,300 行路由按域拆分为 `electron/commandRoutes/{chat,sessions,memory,skills,wiki,system,zotero,orchestration}.ts`；
  - `electron/commands.ts` 仅保留类型定义与 `...DOMAIN_COMMAND_ROUTES` 汇总（目标 $<80$ 行）；
  - 运行 `node scripts/export-ipc-manifest.mjs --check` 与 `node scripts/architecture-check.mjs --tighten`，将 `electron/commands.ts` 从 `architecture-baseline.json` 中正式移除。

### L2 · 数据仓储层（`backend/data/*_repo.py`）单测补齐计划（R185 续篇，P1）

- **现状与痛点（已核实数据）**：
  - `backend/data/` 下共有 **19 个** `*_repo.py` 模块，但 `backend/tests/unit/data_repo/` 下目前仅有 **3 个**测试文件（`test_agent_repo.py`、`test_answer_version_repo.py`、`test_orchestration_repo.py`），**16 个仓储模块（84%）尚无专属契约单测**。
  - 今日合入的 R185（`#1906`/`#1907`）在为 `orchestration_repo.py` 编写单测时，直接捕获了 `TaskRepository.get_ready_tasks` 只在 `CREATED` 子集中查找依赖导致带依赖任务永远无法就绪的严重逻辑缺陷——证明仓储层直连 SQLite 临时库的单测 ROI 极高。
- **落地方案（分三批推进，每批双轨交付）**：
  - **批次 R186（产物与审批）**：`artifact_repo.py`、`artifact_version_repo.py`、`approval_decision_repo.py`（配合 F1 产物迁移同步验收）；
  - **批次 R187（项目与会话）**：`project_repo.py`、`project_material_repo.py`、`project_constraint_repo.py`、`project_milestone_repo.py`、`session_repo.py`、`session_event_repo.py`、`session_todo_repo.py`、`settings_repo.py`；
  - **批次 R188（编排细分仓储）**：`orch_run_repo.py`、`orch_task_repo.py`、`orch_lane_repo.py`、`orch_events_repo.py`、`orch_context_repo.py`。

### L3 · 后端 349 处 `except Exception` 吞异常分级治理与棘轮（P1）

- **现状与痛点**：
  - 后端非测试代码中存在 349 处 `except Exception` 吞异常块，高频文件包括 `backend/wiki/files.py`（9 处）、`backend/orchestration/chat_dispatcher.py`（7 处）、`backend/orchestration/lane_registry.py`（7 处）、`backend/tools/web_render.py`（7 处）、`backend/api/llm_proxy_routes.py`（6 处）。
- **落地方案**：
  1. **三级分类治理**：
     - **A 类（API / 用户请求主链路）**：禁止裸吞，必须转化为领域异常或结构化错误响应；
     - **B 类（事件广播 / 旁路记录 / 降级回退）**：保留异常隔离，但必须记录 `logger.warning(..., exc_info=True)` 并附 `# noqa: BLE001 — <明确降级理由>`（如 `backend/tools/file_tool.py:158`）；
     - **C 类（幂等清理 / `remove_*_listener`）**：统一改用 `contextlib.suppress( SpecificError )`。
  2. **脚本棘轮**：新增 `scripts/check_silent_exceptions.py` 锁定当前未注释的 `except Exception: pass/continue` 数量，只降不增。

### L4 · `main` 与 `release/win7` 双轨防漂移自动化门禁（P1）

- **现状与痛点（今日实战复盘）**：
  - 今日在将 R185（`#1906`）摘樱桃到 `release/win7`（`#1907`）时，`backend/data/orchestration_repo.py:90,269` 的 `Task | None` / `Team | None` 在 `main`（Python 3.11）畅通无阻，但在 `release/win7` CI 被 `scripts/check_py38_compat.py`（PEP 604/585 门禁）拦截。
  - 根因是 `check_py38_compat.py` 仅在 `release/win7` CI 执行，导致 `main` 上的日常提交不断在双轨共享的 `backend/` 文件中埋入 PEP 604 `|` 语法地雷，显著抬高双轨同步成本。
- **落地方案**：
  1. **PEP 604/585 门禁前移至 `main`**：在 `main` 分支的 `ci.yml`（`Architecture check` 或 `Backend (Python)`）中增加一步 `python scripts/check_py38_compat.py`，或在 `pyproject.toml` 的 Ruff 配置中对 `backend/` 启用 `UP006`/`UP007` 禁用规则，确保 `main` 代码天然兼容 `release/win7` 摘樱桃。
  2. **`release/win7` 架构基线收紧**：将 `#1891` 的 `--tighten` 同步应用至 `release/win7`，消除 `win7` 上的残留基线松弛。

### L5 · 后端超大文件减负与 `hex_routes` / `legacy_routes` 双栈收敛（P2）

- **现状与痛点**：
  - `architecture-baseline.json` 中 Top 超大文件仍高于 1,400 行：`backend/api/legacy_routes.py`（2,368 行）、`backend/orchestration/chat_dispatcher.py`（2,258 行）、`backend/data/database.py`（1,962 行）、`backend/api/wiki_routes.py`（1,692 行）、`backend/tools/office_create_tool.py`（1,580 行）、`backend/api/office_routes.py`（1,459 行）。
  - 同时 `backend/api/hex_routes.py` 与 `backend/api/legacy_*_routes.py` 仍重复定义 `POST /chat`、`GET/PUT /settings`、`GET/PUT /preferences/*` 共 5 组路由。
- **落地方案**：
  1. 将 `settings` 与 `preferences` 路由逻辑统一收敛至 `backend/application/services/`，消除 `hex` 与 `legacy` 两侧的重复实现；
  2. 将 `backend/api/office_routes.py`（1,459 行）按职责拆分为 `office_preview_routes.py`、`office_apply_routes.py`、`office_form_routes.py`，每次拆分后运行 `node scripts/architecture-check.mjs --tighten` 永久下调基线配额。

---

## 四、建议执行批次（Roadmap）

1. **第一批（立即可做，P0 核心闭环，约 3–4 天）**：
   - **L1**：`electron/commands.ts` 按域彻底拆分并退出 `architecture-baseline.json`；
   - **U1**：UX-IA R3 批次 C（三套右栏迁 `PanelShell` + 右栏头部瘦身 + `TaskCenter` 浮层退让）；
   - **F1**：`artifacts` 表扩展 `workspace_path`/`format_spec` + 对话产物卡片直通 `OfficeDeliveryDrawer` 验收闭环。
2. **第二批（质量加固与在飞收口，P1，约 3–4 天）**：
   - **F2 + F3**：rebase 合入 `#1626`（Office 版本防冲突）与 `#1010`（`projects_update_allowed_paths`），清零 `electron/ipc-known-gaps.json`；
   - **L4**：`main` 接入 `check_py38_compat.py` + `release/win7` 执行 `architecture-check.mjs --tighten`；
   - **L2（首批 R186）**：补齐 `artifact_repo` / `artifact_version_repo` / `approval_decision_repo` 单测。
3. **第三批（体验深化与存量治理，P1/P2，持续迭代）**：
   - **U2 + F4**：左栏「项目 $
ightarrow$ 会话」合并树（批次 B-2）+ `TrajectoryPane` 二期后端事件源遥测；
   - **U3 + U4 + L3**：`text-[Npx]` 238 处棘轮与 `text-ui-2xs` 替换、`reportActionFailure` 统一错误反馈、后端吞异常分级棘轮；
   - **U5 + L5**：`i18n/{en,zh}.ts` 与 `office_routes.py` 按域拆分、`hex/legacy` 双栈路由收敛。

---

## 六、P0 实施落地记录（2026-10-08）

已在独立工作树 `.worktrees/roadmap-p0-20261008`（`main` 线）与 `.worktrees/roadmap-p0-win7-20261008`（`release/win7` 线）完成第一批高 ROI 项的落地与双轨验证：

1. **L1（IPC 路由表按域彻底拆分）**：
   - 将 `electron/commands.ts` 剩余路由按域拆入 `electron/commandRoutes/{chat,sessions,memory,settings,skills,orchestration,integrations}.ts` 并补齐 `office.ts`、`projects.ts`、`prompts.ts`。
   - `electron/commands.ts` 由 **1,385 行缩减至 49 行**，通过 `node scripts/architecture-check.mjs --tighten` 从 `architecture-baseline.json` 正式移除，全表 235 条 IPC 命令通过 `export-ipc-manifest.mjs --check` 与 89 项契约/单测校验。
2. **F1 + L2-R186（Office 产物直通交付工作台 + 产物仓储契约单测）**：
   - 后端 `artifacts` 表新增 `workspace_path` 与 `format_spec` 列，配套 `runner.py` v5 版本化幂等迁移（`_v5_artifacts_office_columns`）。
   - `ArtifactRepository.record_artifact` 支持 `COALESCE` 幂等保留/刷新 `workspace_path` 与 `format_spec`，`OfficeCreateTool` 在生成文档时透传目标工作区与格式规范。
   - 新增 `backend/tests/unit/data_repo/test_artifact_repo.py`（R186，覆盖 12 种扩展名分类、Office 元数据落盘、同路径幂等更新、跨会话隔离与清理）。
   - 前端 `ArtifactRow` / `ArtifactsSection` 为 `docx/xlsx/pptx/pdf` 产物提供一键打开 `OfficeDeliveryDrawer` 入口，`DeliveryDrawerHost` 支持直接消费 `delivery.ref`。
3. **U1 / U3 / U4（面板最大化空间退让 + 2xs 排版标尺 + 统一显式错误反馈）**：
   - **U1**：`RightPanel.tsx` 顶栏宽度预设按钮升级至 `min-w-[28px] min-h-[28px]`（符合 WCAG 2.5.8 靶区标准）；`TaskCenterWidget.tsx` 在右侧面板或底部工作台最大化时自动收起展开浮层并退让至紧凑边角态（`data-panel-maximized="true"`）。
   - **U3**：`tailwind.config.js` 新增响应式 `text-ui-2xs`（`calc(var(--ui-font-size, 14px) - 3px)`），并在 `RightPanel`、`ArtifactsSection`、`TaskCenterWidget`、`OfficeCapabilityBar` 完成首批字号迁移。
   - **U4**：新增 `src/shared/lib/reportActionFailure.ts`（单测覆盖），接入 `PromptTemplatesTab` 拖拽排序失败回滚提示与 `OfficeCapabilityBar` 引擎探测失败可重试提示条。
---

## 七、P1 第一批落地实施记录（2026-10-08）

### 7.1 P0 双轨合入闭环

- **PR #1910 (`main`)**：已通过全部 CI 门禁并 Squash Merge 合入 `main`（Commit `212f454ca6f130b5cbd17397379884960efb5fe6`）。
- **PR #1911 (`release/win7`)**：已通过全部 Python 3.8 / Electron / 前端门禁并 Squash Merge 合入 `release/win7`（Commit `fcc7377e721ecb4716b5885f1c5db0c094d0b0c9`）。

### 7.2 P1 第一批（F3 + F2 + L4）实施明细

1. **F3（清零最后 2 条 IPC 已知缺口，收口 PR #1010）**：
   - 在 `electron/commandRoutes/projects.ts` 注册 `projects_update_allowed_paths`（`PUT /api/v1/projects/${id}/allowed-paths`），并在 `projects_register` 透传 `allowed_paths` 与 `project_type`。
   - 在 `electron/main.ts` 注册 `wiki_chat_cancel` 命令路由与 `cancelWikiChatStream`（支持 `stream_id` 与 `owner_token` 归属校验，复用流式 `AbortController` 立即中止后端 SSE 请求）。
   - 将 `electron/ipc-known-gaps.json` 的 `frontendUnregistered` 与 `manifestWithoutRoute` 清零（`2 -> 0`），重新导出 `electron/ipc-manifest.json`，并在 `electron/__tests__/ipc-contract.test.ts` 新增两条路由契约单测。
2. **F2（Office 文档版本一致性与 409 冲突/幂等保护，收口 PR #1626）**：
   - 新增 `backend/office/revision.py`（基于 `(size, mtime_ns)` 记忆化的 SHA-256 内容版本戳、单文档进程内写锁、有界幂等重放台账）。
   - `/api/v1/office/update/preview` 返回 `source_revision` / `ops_hash` / `preview_id`；`/api/v1/office/doc/{id}/update` 与 `office_update` 工具支持 `expected_revision`（陈旧版本写入返回 HTTP 409 / `revision_conflict`，原文件零改动）与 `idempotency_key`（重试幂等重放），并在写后显式失效 `read_cache`；新增 `GET /api/v1/office/doc/{id}/revision` 及对应 IPC 命令 `office_doc_revision`。
   - 前端 `OfficePreviewPanel`、`DocxNativePreview`、`OfficeEditPreviewDialog` 切换为按内容 `revision` 键控缓存，409 冲突时提示并自动刷新预览。
3. **L4（Python 3.8 双轨防漂移门禁与架构基线收紧）**：
   - 新增零依赖 AST 门禁脚本 `scripts/check_py38_compat.py` 及单测/全仓契约测试 `backend/tests/unit/test_py38_compat_gate.py`，静态拦截四类破坏 `release/win7` Python 3.8 运行时的语法：缺失 `from __future__ import annotations` 时的 PEP 604/585 注解、运行时 `isinstance/issubclass(..., A | B)`、Pydantic `BaseModel` 字段与 FastAPI 路由参数/返回值中的 PEP 604/585 注解；同时为 `scripts/py38_compat_rewrite.py` 增加 `--fail-on-drift` 退出码支持。
   - 运行 `node scripts/architecture-check.mjs --tighten` 收紧双轨 `architecture-baseline.json` 基线。
---

## 八、P1 第二批落地实施记录（2026-10-08）

### 8.1 P1 第一批双轨合入与在飞 PR 收口

- **PR #1912 (`main`) & PR #1913 (`release/win7`)**：完成 F3（清零 IPC 已知缺口）、F2（Office 版本一致性与 409 冲突/幂等保护）、L4（Python 3.8 语法防漂移门禁与架构基线收紧）双轨交付并合入基线；同时正式关闭已被完整吸收并超集替代的陈旧在飞 PR **#1010** 与 **#1626**。

### 8.2 P1 第二批（L2-R187 + L3 + F4 + U2）实施明细

1. **L2-R187（数据仓储层契约单测全覆盖）**：
   - 新增 `backend/tests/unit/data_repo/test_approval_decision_repo_r187.py`：覆盖 `ApprovalDecisionRepository` 的创建、按 ID/Session/状态查询、幂等状态流转（`pending -> approved/denied/expired`）、批量超期扫描及级联清理。
   - 新增 `backend/tests/unit/data_repo/test_project_repo_r187.py`：覆盖 `ProjectRepository` 的项目登记、路径幂等去重、允许路径（`allowed_paths`）更新、关联会话统计与项目材质（`project_materials`）生命周期（仅 `main` 含 M3 材质扩展列；`release/win7` 适配基础表结构）。
   - 新增 `backend/tests/unit/data_repo/test_session_todo_and_artifact_version_r187.py`：覆盖 `SessionTodoRepository` 的快照原子替换/跨会话隔离，以及 `ArtifactVersionRepository` 的单调递增版本号分配、内容去重与历史回溯。
2. **L3（后端静默异常 AST 棘轮门禁与核心编排层清理）**：
   - 新增零依赖 AST 扫描与棘轮门禁 `scripts/check_silent_exceptions.py`、基线清单 `scripts/silent-exceptions-baseline.json`（全仓锁死 33 处历史存量，核心编排与上下文工程层清零）及契约单测 `backend/tests/unit/test_silent_exception_ratchet.py`。
   - 清理 `backend/context_engineering/compaction.py`、`backend/context_engineering/context_breakdown.py`、`backend/orchestration/chat_dispatcher.py`、`backend/application/services/chat_service.py` 中的 5 处静默 `except Exception: pass`，统一改为 `logger.debug(..., exc_info=True)` 可观测降级日志。
3. **F4（`TrajectoryPane` 二期：耗时分布、角色/工具快筛与复制 JSON）**：
   - 扩展 `src/features/chat/useConversationTrajectory.ts`：新增 `inputTokens` 字段透传与会话级 `summary` 汇总（`totalEntries`、`totalToolCalls`、`totalInputTokens`、`totalOutputTokens`、`totalLatencyMs`、`maxLatencyMs`）。
   - 升级 `src/widgets/chat/TrajectoryPane.tsx`：新增顶部汇总遥测条（`trajectory-summary`）、角色与工具快筛胶囊（`全部 / 用户 / 模型 / 含工具`）、单步相对耗时热度条（`trajectory-latency-bar`）及展开详情一键复制 JSON（`trajectory-copy-json`）。
4. **U2（左栏项目-会话树快捷新建防呆与当前会话高亮）**：
   - 升级 `src/widgets/sidebar/sections/ProjectSection.tsx`：`handleNewChatInProject` 补齐 `410 project_path_missing` 失效目录徽标标记与专属提示（成功创建时自动清除失效标记），并为展开子会话行增加 `aria-current="page"` 语义无障碍标注，同时通过 `architecture-check.mjs --tighten` 将 `ProjectSection.tsx` 基线进一步收紧（`924 -> 923`）。
---

## 九、P2 第三批落地实施记录（2026-10-08）

### 9.1 P1 第二批双轨合入闭环

- **PR #1917 (`main`) & PR #1916 (`release/win7`)**：完成 L2-R187（`approval_decision_repo` / `project_repo` / `session_todo_repo` / `artifact_version_repo` 契约单测）、L3（`check_silent_exceptions.py` AST 棘轮门禁与核心编排层静默异常清理）、F4（`TrajectoryPane` 二期遥测汇总、角色/工具快筛、耗时热度条与复制 JSON）及 U2（左栏项目-会话树快捷新建 410 防呆与当前会话无障碍高亮），100% CI 门禁通过后 Squash Merge 合入 `main`（`d474a0751`）与 `release/win7`（`35f735ce8`）。

### 9.2 P2 第三批（U5 + U3 + L2-R188 + L5）实施明细

1. **U5（`i18n/{en,zh}.ts` 分域拆分并正式退出架构超限基线）**：
   - 将 `src/shared/lib/i18n/zh.ts`（1,290 行）与 `src/shared/lib/i18n/en.ts`（1,324 行）按业务域拆分为 `src/shared/lib/i18n/locales/{zh,en}/{chatAndSider,settingsAndModels,workspaceAndTools}.ts`（每个子文件约 410–438 行，均远低于 800 行新文件上限）。
   - `zh.ts` 与 `en.ts` 收敛为 20 行聚合入口，完整保留 `TranslationKey = keyof typeof zh` 字面量联合类型与 `Record<TranslationKey, string>` 编译期双向完备性校验。
   - 执行 `node scripts/architecture-check.mjs --tighten`，将 `en.ts` 与 `zh.ts` 从 `architecture-baseline.json` **彻底移除**（单次消除 **2,581 行**架构基线配额）。
2. **U3（`check-font-scale.mjs` 字号标尺棘轮门禁 + 50 处高频组件迁移）**：
   - 新增 `scripts/check-font-scale.mjs`、`scripts/font-scale-baseline.json` 与契约单测 `src/shared/lib/__tests__/fontScaleGate.test.ts`，对 `src/` 非测试文件中的硬编码 `text-[Npx]` 实施逐文件只降不增棘轮保护（支持 `--tighten` 与 `--max-slack=0`）。
   - 将 `TrajectoryPane.tsx`、`ContextMeter.tsx`、`TaskTreeSection.tsx`、`ProjectSection.tsx` 四大高频组件中的 **50 处** `text-[10px]` / `text-[11px]` 统一迁移至随 `--ui-font-size` 等比缩放的 `text-ui-2xs`，将全仓基线从 236 处直接压降至 **186 处**（`main`）/ **179 处**（`release/win7`）。
3. **L2-R188（`SessionRepository` / `SessionEventRepository` / `SettingsRepository` 契约单测）**：
   - 新增 `backend/tests/unit/data_repo/test_session_and_settings_repo_r188.py`，覆盖 `SessionRepository`（创建、父子关联、标题搜索、置顶排序、运行态更新、遗留 `running -> failed` 启动恢复、归档与物理清理）、`SessionEventRepository`（单调递增 `seq` 分配、事件回放、`surface_op` JSON 序列化）以及 `SettingsRepository`（白名单校验、字符串/JSON 读写、按分类枚举与删除）。
4. **L5（`backend/api/office_routes.py` 期刊模板子路由拆分减负）**：
   - 将 `backend/api/office_routes.py` 中的期刊模板子系统（5 条端点 + 9 个请求/响应模型）拆出至独立模块 `backend/api/office_journal_routes.py`，通过 `router.include_router` 挂载并保持原模块 `__all__` 导出向后兼容。
   - 执行 `node scripts/architecture-check.mjs --tighten`，将 `backend/api/office_routes.py` 基线永久下调 **251 行**（`1,496 -> 1,245`）。
