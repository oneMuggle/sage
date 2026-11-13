# 147. 项目工作台 IA 与交互（/projects + 治理五章）

**最后更新**: 2026-11-10
**适用分支**: main + release/win7
**关联文档**: [17 前端质量](./17-frontend-quality.md)、[143 项目工作台·规则中心](./143-project-workbench-rules-center.md)、[134 AI 文档工作台](./134-office-ai-workbench.md)、[用户手册 §46](../user-manual/46-project-workbench.md)

---

## 147.1 背景

项目工作台（`/projects` + `/projects/:id`）是用户管理「规则 / 资料 / 文件 / 设置」的主入口。2026-11-09 的真机走查发现两类问题：

- **结构问题**：页面同时渲染多份项目列表、外层 Card 套内层 Card、概览章堆叠 30 个可见按钮、资料章混装四类内容；
- **认知负担问题**：设置页一进入就自动跑 LLM 分析、界面外露内部术语（`M4`、`Embedder: hash (256 维)`、「语料池」、「注入项目上下文第 2 层」）、文件章整章硬编码英文。

本特性按主流 AI 应用（ChatGPT Projects / Claude Projects / Notion）的做法重做信息架构，目标是**一屏一跳、渐进披露、零自动耗时任务**，且不增加任何使用步骤。

改造前实测确认的问题清单见 [用户手册 §46](../user-manual/46-project-workbench.md) 的「改造前的问题」一节；本文只讲实现结构。

## 147.2 设计原则

| 原则 | 落地方式 |
| --- | --- |
| 单一入口 | `/projects` 只保留一份项目列表；侧栏「项目」分区在该路由隐藏 |
| 一屏一跳 | 容器定宽居中（`max-w-[960px]`），消除稀疏空白；整行点击进工作台 |
| 渐进披露 | 高级操作进 `···` 菜单或 `<details>` 折叠区；批量操作需显式进入选择模式 |
| 不打扰 | 设置页不自动调用 LLM；语义检索、Wiki、目录初始化默认折叠 |
| 文案口语化 | 全面替换 L 层 / 审计 / 注入 / 语料池等内部术语 |
| 克制的层级 | 去掉内容外层 `Card p-4`，改用「分区标题 + 间距」 |

## 147.3 模块与职责

| 路径 | 职责 |
| --- | --- |
| `src/pages/ProjectsOverview.tsx` | `/projects` 页：标题行、工具栏（搜索 / 类型 / 状态 / 排序 / 批量）、列表挂载点 |
| `src/widgets/sidebar/sections/WorkbenchProjectList.tsx` | 唯一项目列表实现：行渲染、hover 次级操作、选择模式、空态 |
| `src/widgets/layout/Sidebar.tsx` | `/projects` 路由隐藏内容列「项目」分区（`isProjectsRoute`） |
| `src/widgets/sidebar/sections/useProjectSectionData.ts` | 项目/会话数据源；`backend:ready` 事件补刷（启动竞态修复） |
| `src/pages/governance/GovernanceShell.tsx` | 治理页壳层：头部（返回 / 名称 / 类型徽章 / 路径 / 截止徽章 / 主 CTA）、下划线 Tab、内容区 |
| `src/pages/governance/sections/OverviewSection.tsx` | 概览章：状态行 + 下一步 + 里程碑摘要 + 折叠的项目结构 |
| `src/pages/governance/sections/SettingsSection.tsx` | 设置章：五分区（基本信息 / SAGE.md / AI 初始化 / 类型与版本控制 / 高级） |
| `src/pages/governance/sections/KnowledgeSection.tsx` | 资料章：`项目资料` 与 `AI 记忆` 两个二级 Tab（`?knowledge=` 查询参数） |
| `src/features/project-type/ReferenceManager.tsx` | 文件引用：全量 i18n 化 + 空态引导 + 共享 `Select` |
| `src/features/project-type/StudioMaterialsTabPanel.tsx` | 资料入库 + 资料列表（从 `StudioMaterialsAndProfilePanels.tsx` 拆出） |
| `src/features/project-type/StudioAllowedPathsTabPanel.tsx` | 外部文件夹（只读）面板（同一拆分） |
| `src/features/project-type/SemanticSearchPanel.tsx` | 语义检索面板：独立文件，默认折叠 |
| `src/features/project-type/ProjectBootstrapPanel.tsx` | AI 初始化：新增 `autoStart` 开关，默认 `false`（不自动扫项目） |
| `src/features/project-type/projectFilters.ts` | 列表筛选类型与工具（原 `src/pages/projects/projectOverviewUtils.ts`，重命名并迁到 features 层） |
| `src/features/rules/rulesView.ts` | 新增 `sourceDetail()`：路径型 scope 只显示文件名，全路径进 `title` |
| `src/shared/lib/i18n/locales/{zh,en}/governanceFiles.ts` | 文件引用域词典（新增） |
| `src/shared/ui/Select/Select.tsx` | 共享 Radix `Select`（**未改动**，治理页与文件页统一复用） |

## 147.4 `/projects` 列表

### 147.4.1 结构

```
┌ 项目                                   [+ 新建项目] ┐
│ 管理项目规则、资料与会话；点击项目进入工作台。        │
│ [搜索项目名称、路径或描述…] [类型 ▾] [活跃|归档] [排序 ▾] [批量管理] │
│ 📁 LLM_Simple   编码 · 研发实现   7 个会话   最近 2h   │
│ 📁 ArenaX       编码 · 规划       2 个会话             │
└───────────────────────────────────────────────────┘
```

- 容器 `mx-auto w-full max-w-[960px] px-6 py-6`；此前页面外层为 `flex-1` 的朴素 `<ul>`，项目少时被拉满剩余高度，形成「列表上方大块空白」。该朴素列表与底部完整列表**同时存在**，本次删除朴素列表，只保留 `WorkbenchProjectList`。
- 列表行为不变的部分：整行点击打开工作台、hover 出现「新建会话 / 开始会话」主操作与 `···` 菜单（新建会话 / 归档 / 移除 / 在文件夹中显示 / 复制路径等）、行内可展开会话子列表、拖放注册项目目录。

### 147.4.2 批量模式

复选框默认不渲染，避免干扰浏览。点「批量管理」进入选择模式：

- 工具栏切换为「取消选择」+「归档所选（N）」，`N === 0` 时归档按钮禁用；
- 行首出现选择框（`projects-overview-select-<id>`）；
- 离开选择模式自动清空选择集；
- 归档走 `projectApi.setProjectStatus(id, 'archived')`，完成后 `refreshKey` 自增触发列表刷新。

### 147.4.3 启动竞态修复

`useProjectSectionData` 原来只在挂载时 `refresh()` 一次；后端未就绪时该请求失败且不再重试，导致侧栏与工作台项目区**永久显示空态**（主区却有数据）。修复方式：

```ts
// 后端就绪事件到达后补一次刷新
void api.listen('backend:ready', () => { if (!cancelled) void refresh(); })
```

`api.listen` 不可用（非 Electron 环境）时直接跳过，不影响其他行为。

## 147.5 治理页壳层

`GovernanceShell` 由「外层 Card + pill Tab」改为「头部 + 下划线 Tab + 裸内容区」：

| 位置 | 改造 |
| --- | --- |
| 头部左侧 | 返回工作台 / 项目名 / 类型徽章 / 路径（`max-w-[40ch] truncate`，全路径进 `title`）/ 截止徽章 |
| 头部右侧 | **唯一主 CTA**「开始会话」（`governance-header-cta`），加载中显示「正在打开…」 |
| Tab | 下划线式（`border-b-2` + `border-primary`），与主流设置页一致；`role="tab"` / `aria-selected` 保留 |
| 内容区 | 去掉外层 `Card p-4`，每个 Section 自行用「分区标题 + 间距」组织 |

`governanceTabs.ts` 的 `governanceHref` / `parseGovernanceTab` 与深链 `?tab=` 语义不变；旧深链 `?knowledge=rules` 仍重定向到 `?tab=rules`。

## 147.6 概览章

按「项目现在什么状态 → 我下一步该做什么」重排：

| 区块 | testid | 内容 |
| --- | --- | --- |
| 状态行 | `project-home-summary` | 类型 / 当前阶段 / 初始化进度（`done/total`）；未初始化时给「继续初始化」次按钮 |
| 下一步 | `project-next-actions` | 最多 3 条行动项，每条「一句文案 + 一个按钮」（`project-next-action-<id>`）；全部完成时显示「一切就绪，可以开始工作了。」 |
| 里程碑摘要 | `project-milestone-summary` | 总体进度 + 完成/进行/阻塞计数 + 最近 3 条未完成项（`project-milestone-recent`） |
| 当前阶段 | `project-current-stage-section` | 当前阶段与「分解任务」入口 |
| 项目结构 | `project-structure` | `<details>` 折叠，放工程概览等低频信息 |

原跨页动作（`+规则` / `+记忆` / `+资料` / 「存为资料」）从概览移除，回到规则章与资料章执行；「文件整理建议」与工程概览下沉到折叠区。

## 147.7 设置章

五个分区，**零自动耗时任务**：

| # | 分区 | 说明 |
| --- | --- | --- |
| 1 | 基本信息 | 项目描述 + 会话指令；这两项作为每次会话的背景传给 AI |
| 2 | 项目总纲（SAGE.md） | `<details>` 折叠，点「编辑项目总纲」展开编辑区，不再常驻大文本框 |
| 3 | AI 初始化 | `ProjectBootstrapPanel`，`autoStart` 默认 `false`；点「分析项目」才触发 scan + suggest |
| 4 | 项目类型与版本控制 | 形态 / 阶段 / VCS 三个下拉 + 「推进至下一阶段」按钮 |
| 5 | 高级设置（折叠） | 目录初始化 · 外部文件夹（只读）· 工程概览 · 项目 Wiki · 快照与导出台账 |

### 147.7.1 `autoStart` 开关

`ProjectBootstrapPanel` 新增可选 prop `autoStart?: boolean`（默认 `false`）：

- `false` → 首屏展示「未分析」状态，用户点「分析项目」才发起 `/bootstrap/scan`；
- `true` → 保持旧行为（进入页面即分析），供仍依赖自动流程的调用方使用。

设置页与概览页均使用默认关闭。

### 147.7.2 术语替换

| 旧文案 | 新文案 |
| --- | --- |
| Description & System Instructions | 项目描述与会话指令 |
| 注入项目上下文第 2 层… | 每次会话自动带给 AI 的项目背景 |
| 跨目录只读白名单 | 外部文件夹（只读） |
| 一键初始化目录与规范 | 补齐项目目录与说明文件 |

## 147.8 资料章

二级 Tab 由 `?knowledge=materials|profile` 驱动（`governance-knowledge-materials` / `governance-knowledge-profile`）：

- **项目资料**：`StudioMaterialsTabPanel` —— 入库表单（工作区相对路径 / 粘贴文本）+ 已入库资料列表（启用开关 / 预览 / 重建索引 / 删除 / 复制 Markdown）。
- **AI 记忆**：`StudioProfileTabPanel` —— 原有的用户画像编辑区。

语义检索（`SemanticSearchPanel`）改为 `semantic-search-collapsible` 折叠区，内部术语（`M4`、`Embedder: hash (256 维)`）下沉到高级信息；Git 状态与 Wiki 生成移出资料章（Git 状态并入概览折叠区，Wiki 生成并入设置高级区）。

`StudioMaterialsAndProfilePanels.tsx` 拆分后各文件均 < 800 行上限；新拆出的两个面板文件分别为 346 / 173 行。

## 147.9 文件章 i18n

新增词典域 `governance.files.*`（`src/shared/lib/i18n/locales/{zh,en}/governanceFiles.ts`，中文为类型源）：

| 键 | 中文 |
| --- | --- |
| `governance.files.subtitle` | 文件引用让 AI 以只读方式访问项目之外的资源。 |
| `governance.files.scan.idle` / `.busy` | 重新扫描 / 扫描中... |
| `governance.files.create.relPath` | 项目相对路径 * |
| `governance.files.create.targetPath` | 目标绝对路径 * |
| `governance.files.create.alias` | 别名 |
| `governance.files.create.kind` | 类型 |
| `governance.files.create.kind.directory` / `.file` / `.symlink` | 文件夹 / 文件 / 符号链接 |
| `governance.files.create.submit` / `.submitting` | 新增引用 / 添加中... |
| `governance.files.list.loading` | 正在加载引用... |
| `governance.files.list.empty` | 暂无引用。可在上方新增，或点击「重新扫描」识别项目中的符号链接。 |
| `governance.files.row.created` | 创建于 |
| `governance.files.confirm.title` | 删除引用？ |
| `governance.files.confirm.messageTail` | 将被移除，源文件不会被删除。 |

`ReferenceManager` 原有 `data-testid` 全部保留（`reference-input-kind` / `reference-input-rel-path` / `reference-input-target-path` / `reference-input-alias` / `reference-create-button` / `reference-scan-button` / `reference-row-<id>` / `reference-delete-<id>` / `reference-list-empty` / `reference-error`）。

## 147.10 规则章文案收敛

只改显示层，不动数据模型、API 与筛选逻辑：

- 新增 `sourceDetail(entry)`（`src/features/rules/rulesView.ts`）：
  - 全局层 → 返回 `null`（全局规则只有唯一来源，行内无需重复标注）；
  - scope 是路径（含 `/` 或 `\`）→ 只显示文件名，完整路径进 `title`；
  - 其余 scope（阶段名等）→ 原样显示。
- `RuleRow` / `EffectiveRulesDrawer` 行内改用 `sourceDetail()`，去掉与分组标题重复的来源名。
- 冲突计数加 tooltip，说明「同一分类下内容不一致的规则」。
- 「查看最终生效规则」→「查看规则生效顺序」。

## 147.11 共享 `Select` 迁移的三个坑

治理页与文件页的原生 `<select>` 统一迁到 `src/shared/ui/Select/Select.tsx`（Radix 封装）。迁移中踩到的三个坑：

1. **`SelectValue` 必须显式传 children。** Radix 只在 `SelectContent` 挂载时把选中项文本注入触发器的 value 节点；不传 children 时收起态标签为空或不确定。做法是 `<SelectValue>项目类型：{label}</SelectValue>`，把标签渲染责任交给调用方。
2. **Radix 拒绝空字符串 `value`。** 「阶段：未设置」不能用 `value=""`，改用哨兵值 `NO_STAGE_VALUE = '__none__'`，在 `onValueChange` 里映射回 `''`。
3. **jsdom 下的指针手势。** Radix Select 依赖 `hasPointerCapture` / `setPointerCapture` / `scrollIntoView` / `ResizeObserver`，jsdom 均未实现，测试里需要 polyfill；打开用 `pointerDown(trigger, { button: 0, pointerType: 'mouse' })`，选中需 `pointerDown` → `pointerMove` → `pointerUp` 且 `clientX/clientY` 偏移 > 10px（否则触发 Radix 的拖拽展开保护）。

## 147.12 测试与门禁

| 门禁 | 结果 |
| --- | --- |
| `tsc --noEmit` | 通过 |
| Vitest 全量 | 7162 通过（`ArenaAccounts` 一例并发超时偶发失败，单独复跑 8/8 通过，与本改动无关） |
| `node scripts/architecture-check.mjs` | 通过（97 基线文件，无新增超限项；`PlaybookCard.tsx` 行数基线 825 → 853） |

新增/更新的测试文件：

| 文件 | 覆盖 |
| --- | --- |
| `src/pages/__tests__/ProjectsOverview.test.tsx` | 单列表渲染、搜索/筛选/排序、批量归档、空态 |
| `src/features/project-type/__tests__/ReferenceManager.test.tsx` | 中文文案、空态、共享 `Select` 切换类型 |
| `src/pages/governance/__tests__/GovernanceShell.test.tsx` | Tab 标签与下划线激活态、头部 CTA |
| `src/pages/governance/GovernanceShell.legacy.test.tsx` | 项目类型下拉（Radix 手势）、jsdom polyfill |
| `src/pages/governance/__tests__/KnowledgeSection.test.tsx` | 资料章只渲染入库/列表、语义检索折叠、Git 状态不在本页 |
| `src/features/project-type/__tests__/ProjectBootstrapPanel.test.tsx` | 默认不自动请求 suggest，手动「分析项目」触发 |
| `src/features/rules/__tests__/rulesView.test.ts` | `sourceDetail()`（路径/非路径/全局层） |

## 147.13 双分支同步

全部为纯前端改动。按里程碑逐个 cherry-pick 到 `release/win7`（**不合并 win7 到 main**）：

| 提交 | 内容 |
| --- | --- |
| `30a47676c` | 方案文档 |
| `48ddf7536` | M1 `/projects` 单列表 |
| `645d5be7d` | M2 概览章重组 |
| `2b6c6bc06` | M3 设置章重组 |
| `c4de89b4e` | M4 文件章 i18n |
| `fff7c38f7` | M6 资料章重组 |
| `56a33d5a4` | M7 规则页文案 |
| `affff7f5a` | M5 壳层视觉统一 |

预计冲突点：i18n 聚合文件（`zh.ts` / `en.ts`）与 `ProjectsOverview.tsx`，按 win7 分支实际行号重应用。win7 的技术手册编号独立（本次为 §151），用户手册编号与 main 一致（§46）。

## 147.14 AI 分析异步化与缓存（2026-11-11）

项目工作台创建向导第一步触发 `POST /projects/analyze`（画像采集 + LLM 治理报告）。此前 `profile_project()` 在 FastAPI async handler 内同步运行，阻塞整个事件循环，导致分析期间其他页面（侧栏、聊天、内存浏览）的 API 请求无法处理，表现为"AI 分析卡住其他模块"。

### 147.14.1 根因

- `profile_project()` 为同步函数，调用链中遍历目录 + 读文件 + subprocess 跑 git，单次耗时数百 ms 到数秒。
- 在 async handler 中直接 `await` 等于把事件循环卡住，其他请求的协程无法让出 CPU。
- LLM 分析阶段 `agent.analyze(profile)` 是 async（HTTP I/O），但整体链路无超时保护，LLM 卡死会让请求永远挂起。

### 147.14.2 后端修复（`backend/api/project_routes.py`）

| 措施 | 实现 |
| --- | --- |
| 画像采集让出事件循环 | `loop.run_in_executor(None, lambda: profile_project(path))`，线程池执行 |
| 结果缓存 | 进程内 dict，key = `path:git_sha`，TTL 1 小时，最多 50 项；非 git 目录不缓存 |
| 硬超时 | `asyncio.timeout(180)` 包裹画像 + LLM 整段，避免 LLM 挂死请求永不返回 |
| 缓存失效 | git commit 变化自动失效；TTL 过期自动淘汰；LRU 兜底 |

缓存命中时 `POST /projects/analyze` 秒回，重复分析同一 git 状态的项目不再消耗 LLM token。

### 147.14.3 前端修复（`src/features/project-type/ProjectAnalysisWizard.tsx`）

- Electron IPC 不支持 AbortSignal，用 `Promise.race` 实现前端软超时（60s）。
- 超时后显示错误横幅，用户可重试。
- 分析进行中显示「取消」按钮，用户可主动中止等待（后端仍在跑，但前端不再阻塞）。

### 147.14.4 测试与门禁

| 门禁 | 结果 |
| --- | --- |
| ruff | 通过（新增 `check=False` 修 PLW1510） |
| `node scripts/architecture-check.mjs` | 通过（`project_routes.py` 1298 → 1369，ratchet 补账） |
| Backend (Python 3.10) | 通过 |
| Backend (Python 3.8, Win7) | 通过（PEP 604/585 护栏 + py38 AST 扫描通过） |
| Frontend (TypeScript) | 通过 |
| Electron build + smoke | 通过 |

### 147.14.5 双分支同步

| 分支 | PR | 合并提交 |
| --- | --- | --- |
| main | #3037 | `b896d9191` |
| release/win7 | #3039 | `2ac9da704`（cherry-pick，架构基线冲突手动解） |

win7 侧的 cherry-pick 冲突集中在 `architecture-baseline.json`：保留 win7 的 `project_ai_routes.py: 861` / `project_schemas.py: 829`，仅更新 `project_routes.py` 到当前行数。
