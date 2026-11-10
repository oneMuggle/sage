# 项目工作台 UI 优化方案（/projects + 概览 + 设置 + 资料 + 文件 + 规则）

**日期**: 2026-11-09
**状态**: 方案待确认，未实施
**分支**: `feat/project-workbench-ui-polish`（main）
**同步计划**: 全部为纯前端改动，实施后 cherry-pick 到 `release/win7`

## 1. 背景与目标

### 1.1 用户诉求

- 项目工作台（`/projects`）样式怪：项目列表上方有大块空白
- 治理页「概览」「设置」两章混乱，控件多、术语重
- 治理页「文件」章仍为英文界面
- 参考主流 AI 应用（ChatGPT Projects / Claude Projects / Notion）的简洁做法
- **不增加用户使用负担**：少操作、少等待、少术语

### 1.2 实测确认的现状问题

以下均基于 2026-11-09 对真实桌面端的截图与代码核对：

| # | 问题 | 证据 |
|---|---|---|
| 1 | `/projects` 页面同时渲染**两份项目列表**：上半部分是仅显示名称的朴素 `<ul>`，下半部分（页面底部）再渲染一份完整的 `WorkbenchProjectList` | `src/pages/ProjectsOverview.tsx:157-173` |
| 2 | 上方朴素列表容器为 `flex-1`，项目少时撑满剩余高度，形成「项目列表上方大块空白」 | `src/pages/ProjectsOverview.tsx:157` |
| 3 | 概览章堆叠 StatusCard + Playbook 卡 + 里程碑组件 + 工程概览，可见按钮约 30 个；术语如「进度存项目记忆」「阶段分布存为资料」「+规则/+记忆/+资料」 | `src/pages/governance/sections/OverviewSection.tsx:179-208`；截图 |
| 4 | 设置章一进入就**自动触发 LLM 分析**（10–30 秒），并常驻一个巨大的 SAGE.md 文本框；「Description & System Instructions」「注入项目上下文第 2 层」等术语外露 | `src/features/project-type/ProjectBootstrapPanel.tsx:86-87`；`SettingsSection.tsx:278-306`；截图 |
| 5 | 文件章全部硬编码英文：`File references grant read-only access to external resources.`、`Rescan`、`Add reference`、`Directory`、`Loading references…` 等 | `src/features/project-type/ReferenceManager.tsx:45-63,118-260` |
| 6 | 左栏「项目」分区在启动竞态下永久显示「暂无项目」，而主区已有 3 个项目；同一页面存在第三份项目入口 | `useProjectSectionData.ts:86-88`（仅挂载时请求一次，后端未就绪失败后不再重试）；截图 |
| 7 | 页面内嵌套边框过多：外层 `Card p-4` 包住所有章节，章节内再套带边框小卡，视觉噪音大 | `GovernanceShell.tsx:160-184` |
| 8 | 资料章把「项目资料 + 语义检索 + Git 状态 + Wiki 生成」混在一页；外露内部里程碑 `M4` 与技术词（`Embedder: hash (256 维)`、「语料池」、「索引统计存到项目记忆」、「提交转规则护栏」） | `KnowledgeSection.tsx:58-70`；`StudioMaterialsAndProfilePanels.tsx:608,779`；截图 |
| 9 | 规则章整体清晰可用（刚由 PR #2952 重构）；仅来源路径过长、个别按钮文案偏术语，属于微调 | `RulesPanel.tsx`；截图 |
| 10 | 概览页的阶段检测横幅（「检测到可能已进入…置信度 90%」）与「文件整理建议」被淹没在堆叠控件中 | `OverviewSection.tsx`；截图 |

### 1.3 目标

1. `/projects` 只保留**一份**项目列表，一屏内可完成「找项目 → 打开 → 新建会话」。
2. 治理页概览默认只呈现「项目在哪、下一步做什么」，高级操作全部渐进披露。
3. 设置页零自动耗时任务；术语全部口语化；每个分区只有一个保存动作。
4. 文件章全中文，字段带可理解的说明与空态引导。
5. 资料章只保留「添加资料 + 资料列表」，语义检索默认折叠，Git 状态与 Wiki 生成移出。
6. 规则章仅做文案收敛，不改功能与数据。
7. 顺带修复左栏项目区启动空态竞态，消除三处重复入口。

## 2. 参考原则（主流 AI 应用）

| 原则 | 主流做法 | 本项目落地 |
|---|---|---|
| 单一列表 | ChatGPT Projects 只有一套项目列表 | 删除 `/projects` 底部重复列表 |
| 一屏一跳 | 列表行整行可点，hover 才出现次级操作 | 行点击进治理页；hover 显示「新建会话 / ···」 |
| 渐进披露 | 设置项分组折叠，高级项默认收起 | 高级操作统一进折叠区或「···」菜单 |
| 不打扰 | 不自动跑长任务 | 设置页不再自动调用 LLM，改为手动「生成建议」 |
| 文案口语化 | 不用内部术语 | 全面替换 L 层、审计、注入等词汇 |
| 克制的视觉层级 | 分区标题 + 间距，而非层层边框 | 去掉外层 Card，改为分区 |

## 3. 方案设计

### 3.1 `/projects` 项目工作台（M1）

**信息架构**

```
┌──────────────────────────────────────────────┐
│ 项目（3）                        [+ 新建项目] │
│ 搜索项目…    [全部类型 ▾] [活跃|归档] [排序 ▾] │
├──────────────────────────────────────────────┤
│ 📁 LLM_Simple   编码 · 研发实现      7 个会话 │
│    /home/fz/project/LLM_Simple       最近 2h │
│  📁 ArenaX     编码 · 规划            2 个会话 │
│  📁 111        未分类                 1 个会话 │
└──────────────────────────────────────────────┘
```

- 容器：`max-w-[960px] mx-auto px-6 py-5`，消除整行铺满与稀疏空白。
- 标题行：`项目` + 数量 + 右侧主按钮「新建项目」（复用 `AddProjectDialog`）。
- 工具栏：搜索（flex-1）+ 类型筛选（chips 或共享 `Select`）+ 活跃/归档分段 + 排序；窄窗口换行。
- 列表：单份 `ProjectRow`（从 `WorkbenchProjectList` 行设计提取），包含：文件夹图标、名称、类型徽章、阶段徽章、路径（单行省略）、会话数、最近活动；整行点击进入治理页；hover 显示「新建会话」+「···」菜单（打开 / 新建会话 / 在文件夹中显示 / 复制路径 / 归档 / 移除）。
- 批量：默认**不显示**复选框；点「批量管理」进入选择模式后，顶部出现上下文操作条（归档所选 N 项）。离开选择模式自动清空。
- 空态：图标 + 「还没有项目」+ 主按钮「新建项目」+ 次按钮「导入已有目录」。
- **删除** `ProjectsOverview.tsx:166-173` 的底部 `WorkbenchProjectList` 区块。
- 左栏：`/projects` 路由下隐藏内容列的「项目」分区（该页本身即项目列表），并修复 `useProjectSectionData` 的启动竞态：监听 `backend:ready` 事件（`api.listen('backend:ready')`），若项目列表为空则重试；或在失败后 3 秒退避重试一次。

**保留的 testid**：`projects-overview`、`projects-overview-search`、`projects-overview-type`、`projects-overview-status-active|archived`、`projects-overview-sort`、`projects-overview-archive`、`projects-overview-row-<id>`、`projects-overview-empty`，便于现有测试低成本迁移。

### 3.2 治理页概览章（M2）

**目标**：默认只回答两个问题——「这个项目现在什么状态」「我下一步该做什么」。

```
┌ 项目状态 ────────────────────────── [开始会话] ┐
│ 编码 · 当前阶段：研发实现     初始化 5/5 已完成 │
├ 下一步 ─────────────────────────────────────── ┤
│ ● 补齐当前阶段交付物         [去处理]          │
│ ● 完成 2 个待办里程碑        [查看]            │
├ 里程碑进度 ─────────────────── [查看全部 →]   │
│ ▓▓▓▓░░░░ 35%   完成 3 · 进行 2 · 阻塞 0        │
│ 最近：架构设计 ✓ / 模块划分 ○ / 联调 ○          │
└────────────────────────────────────────────────┘
▶ 项目结构（工程概览，默认折叠）
```

- **StatusCard**：压缩为一行三列（类型/阶段、初始化进度、最近活动）；「开始会话」主按钮移到卡片右上或页面头部，只保留一个主 CTA。
- **下一步**（新增组件 `NextActionsCard`）：最多 3 条，来自 bootstrap 未完成项、当前阶段待补交付物、未完成里程碑；每条一行文案 + 一个按钮。全部完成时显示「一切就绪，开始会话」。
- **里程碑**：默认只显示总体进度条、完成/进行/阻塞计数、最近 3 条（含状态图标）；单行操作只保留「标记完成」，其余（复制 / +规则 / +记忆 / +资料）收进每行「···」；「管理全部」展开原 `MilestoneManager`。
- **Playbook/规程卡**：保留阶段条与完成度；顶部操作收敛为「检查」主按钮 + 「···」（AI 检查 / 导出 / 更多）；去掉长时间 spinner 占位，改为标题行内小状态。
- **阶段检测横幅**（「检测到可能已进入 X 阶段，置信度 90%」）：作为「下一步」区的第一条行动项呈现（确认推进 / 保持当前），不再单独占一条横幅。
- **文件整理建议**：整节移出概览，放到设置章「高级」折叠区（或资料章独立折叠区），避免与主任务流竞争注意力。
- **工程概览 `PolymorphicArchetypeCards`**：移入默认折叠的「项目结构」details，避免与主任务流竞争注意力。
- 所有「+规则/+记忆/+资料/存为资料」类跨页动作从概览移除，回到各自章节（规则/资料）执行。

### 3.3 治理页设置章（M3）

**目标**：零自动耗时任务、零术语、每区一个保存动作。

分区顺序：

1. **基本信息**：项目描述（单行/多行）+ 会话指令（`instructions`），仅在有改动时启用「保存」；保存成功显示「已保存」。
2. **项目总纲（SAGE.md）**：默认显示摘要与状态（存在/不存在、行数）；「编辑」打开对话框（`Dialog` + `Textarea`），不再常驻大文本框。「生成草稿」为次按钮。
3. **AI 初始化**：不再进入页面自动扫描；先展示已保存的 `bootstrap_state`（若存在），按钮「重新分析项目」按需触发 scan + suggest；分析过程在原卡片内显示两步进度，失败明确提示并保留手动模板入口。
4. **项目类型与版本控制**：形态下拉、阶段下拉 + 推进按钮、VCS 下拉，合并为一行紧凑控件。
5. **高级（默认折叠）**：目录白名单、一键初始化目录、类型转换、快照、治理快照/JSON 导出。
- 删除「项目规程与阶段管理已移至概览页」这类迁移说明卡片（`PlaybookNote`），改为概览页内的隐式跳转。
- 术语替换：
  - `Description & System Instructions` → `项目描述与会话指令`
  - `注入项目上下文第 2 层…` → `每次会话自动带给 AI 的项目背景`
  - `跨目录只读白名单` → `外部文件夹（只读）`
  - `一键初始化目录与规范` → `补齐项目目录与说明文件`
- `ProjectBootstrapPanel` 增加 `autoStart?: boolean`（默认 `false`），设置页与概览页按需启动；保留显式点击加载路径，扫描/建议两步逻辑不变。

### 3.4 文件章中文化 + 引导（M4）

- 新增 i18n 域 `src/shared/lib/i18n/locales/{zh,en}/governance.ts`，键前缀 `governance.files.*`。
- `ReferenceManager.tsx` 全部硬编码英文替换为 `t()`：

| 现文案 | 中文 |
|---|---|
| File references grant read-only access to external resources. | 文件引用让 AI 以只读方式访问外部文件夹，不会修改其中内容。 |
| Rescan / Scanning… | 重新扫描 / 扫描中… |
| Add reference / Adding… | 添加引用 / 添加中… |
| Project-relative path * | 项目内路径 *（如 `data/cases`） |
| Target absolute path * | 目标绝对路径 *（如 `/home/user/external/cases`） |
| Alias | 别名 |
| Type / Directory / File / Symlink | 类型 / 文件夹 / 文件 / 链接 |
| Loading references… | 正在加载引用… |
| No references yet. Add one above, or click "Rescan"… | 还没有文件引用。可在上方添加，或点「重新扫描」识别项目内的链接目录。 |
| created <date> | 创建于 <日期> |
| Delete reference? … | 删除该引用？…（底层文件不会被删除） |
| — | 空态增加主按钮「添加引用」；段落标题为「文件引用」 |
- 日期格式化复用 `formatRelativeTime` 或本地化 `formatCreatedAt`（`YYYY-MM-DD HH:mm` 保持不变即可，但前缀中文）。
- 同步更新 `ReferenceManager.test.tsx`：保留 testid，补充中文文案断言。

### 3.5 壳层与视觉统一（M5）

- `GovernanceShell`：
  - 头部保持一行：返回、项目名、类型徽章、路径、截止徽章；右侧常驻主 CTA（开始会话）。
  - Tab 改为下划线式（与主流设置页一致），随头部 `sticky top-0`，内容独立滚动；或保留 pill 但统一高度与字号。推荐下划线式，降低「一排按钮」的视觉重量。
  - 去掉内容外层 `Card p-4`，每个 Section 自己用「分区标题 + 间距」组织，减少边框嵌套。
- 统一原生 `<select>` 为共享 `Select` 组件；统一按钮尺寸（`size="sm"` 为默认）。
- 概览/设置/文件的空态、错误态文案统一为「一句话说明 + 一个主操作」。

### 3.6 治理页资料章重组（M6）

**目标**：资料页只回答一件事——「项目里有哪些资料，我要怎么加」。

现状问题（2026-11-09 截图）：
- 同一页混放四类内容：项目资料入库、语义检索（含 `M4` 内部标签、`Embedder: hash (256 维)`、快捷检索预设、Top N 等）、Git 状态（分支/修改数/提交记录及「提交转规则护栏」「保存提交摘要到 AI 记忆」「提交存为资料」等跨域按钮）、Wiki 生成。
- 术语外露：「语料池」「索引统计存到项目记忆」「索引统计存为资料」「提交转规则护栏」。

**方案**

```
[项目资料] [AI 记忆 (N)]
┌ 添加资料 ──────────────────────────────────┐
│ 从工作区文件入库： [相对路径…]   [入库]      │
│ 或粘贴文本：       [                   ]   │
│                                   [添加文本资料] │
├ 已入库资料 ────────────────────────────────┤
│ 📄 合同.docx    32 KB    2026-11-09  [删除] │
│ …                                          │
└────────────────────────────────────────────┘
▶ 语义检索（默认折叠，展开后显示检索框与结果）
```

- **资料页主区**只保留：入库表单（工作区路径 / 粘贴文本）+ 已入库资料列表 + 空态引导。
- **语义检索**：从 `StudioMaterialsTabPanel` 中拆出 `SemanticSearchPanel`，改为默认折叠的「语义检索」details（或资料页右侧抽屉）；删除 `M4` 标签与 `Embedder: hash (256 维)` 展示（可保留在「高级信息」hover/`title` 中）；「索引统计存到项目记忆 / 存为资料」两个沉淀按钮收进「···」菜单。
- **Git 状态**：从资料页移入概览章「项目结构」折叠区下方（同属项目现状参考信息）；「提交转规则护栏 / 提交存为资料 / 保存到 AI 记忆」分别改为跳转链接（去规则页 / 资料页），不在 Git 区直接执行跨域写入。
- **Wiki 生成**：移入设置章「高级」折叠区（生成类操作低频）。
- 拆分 `StudioMaterialsAndProfilePanels.tsx`（785 行，接近 800 行上限）：抽出 `SemanticSearchPanel` 到独立文件；调整后各文件 < 400 行。
- 文案：「项目资料与文献语料池」→「项目资料」；「入库」→「添加」；保留「只读/受控」含义用一句话说明（「添加到 Sage 的资料会被索引，仅用于本项目会话」）。

### 3.7 规则页文案收敛（M7）

规则页（PR #2952 重构结果）整体可用，只做低风险微调：

- 行内来源路径 `/home/fz/project/LLM_Simple/SAGE.md` 改为只显示文件名 `SAGE.md`，`title` 保留完整路径。
- 分组标题「项目总纲 · 6」已带来源，行内重复的来源名可省略。
- 「查看最终生效规则」→「查看规则生效顺序」；「AI 帮我改」保留（已被用户熟悉）。
- 冲突提示文案「6 个冲突」补充 tooltip：「同一分类下内容不一致的规则」。
- 不改数据模型、不改 API、不改筛选逻辑。

## 4. 涉及文件

### 前端（修改）

| 文件 | 改动 |
|---|---|
| `src/pages/ProjectsOverview.tsx` | 重写为单列表布局；删除底部重复列表；新增批量模式与空态 |
| `src/widgets/sidebar/sections/WorkbenchProjectList.tsx` | 行组件抽为可复用 `ProjectRow`（新页面与侧栏共用），或新增 `ProjectRow.tsx` |
| `src/widgets/sidebar/sections/SidebarProjectList.tsx` | `/projects` 路由隐藏；启动竞态重试接线 |
| `src/widgets/sidebar/sections/useProjectSectionData.ts` | 监听 `backend:ready`，失败退避重试一次 |
| `src/pages/governance/GovernanceShell.tsx` | 头部 CTA、下划线 Tab、去外层 Card |
| `src/pages/governance/sections/OverviewSection.tsx` | 重组为状态 / 下一步 / 里程碑 / 折叠项目结构 |
| `src/pages/governance/sections/SettingsSection.tsx` | 五分区重组；高级折叠；术语替换 |
| `src/pages/governance/sections/FilesSection.tsx` | 标题与说明 |
| `src/features/project-type/ReferenceManager.tsx` | 全量 i18n 化 + 空态引导 |
| `src/features/project-type/ProjectBootstrapPanel.tsx` | 新增 `autoStart` 开关，默认不自动跑 LLM |
| `src/pages/governance/sections/KnowledgeSection.tsx` | 重组：只保留资料入库 + 列表；Git 状态与 Wiki 生成移出 |
| `src/features/project-type/StudioMaterialsAndProfilePanels.tsx` | 拆出 `SemanticSearchPanel`（785 行 → 各 < 400 行）；资料面板术语中文化 |
| `src/features/project-type/GitStatusWidget.tsx` | 移入概览「项目结构」折叠区；跨域按钮改为跳转 |
| `src/features/project-type/WikiGenerationPanel.tsx` | 移入设置章「高级」折叠区 |
| `src/features/rules/rulesView.ts` | 新增 `sourceDetail()`：路径型 scope 只显示文件名，全路径进 `title` |
| `src/features/rules/RuleRow.tsx` | 行内移除重复来源名，改用 `sourceDetail()` 显示来源细节 |
| `src/features/rules/EffectiveRulesDrawer.tsx` | 生效顺序抽屉行内改用 `sourceDetail()` |
| `src/features/rules/RulesPanelSections.tsx` | 冲突计数加 tooltip；「查看规则生效顺序」按钮文案 |
| `src/features/playbook/PlaybookCard.tsx` | 操作收敛（如 UI 文案与按钮位于此组件） |
| `src/features/project-type/ProjectOverviewWidgets.tsx` | 仅收敛入口展示，不改能力 |
| `src/shared/lib/i18n/locales/zh/governance.ts` | 新增中文字典 |
| `src/shared/lib/i18n/locales/en/governance.ts` | 新增英文字典 |
| `src/shared/lib/i18n/zh.ts` / `en.ts` | 聚合新域 |

### 前端（新增）

| 文件 | 说明 |
|---|---|
| `src/pages/projects/ProjectRow.tsx` | 统一的单行项目组件（名称/徽章/路径/会话数/最近活动/hover 操作） |
| `src/pages/governance/sections/NextActionsCard.tsx` | 「下一步」聚合卡 |
| `src/features/project-type/SemanticSearchPanel.tsx` | 从资料面板拆出的语义检索折叠区（术语中文化） |
| `src/shared/lib/i18n/locales/zh/governance.ts` + `en` | 治理与文件引用文案 |

### 测试（修改/新增）

| 文件 | 覆盖 |
|---|---|
| `src/pages/__tests__/ProjectsOverview.test.tsx` | 单列表渲染、搜索/筛选/排序、批量归档、空态；断言不再渲染两份列表 |
| `src/pages/projects/__tests__/ProjectRow.test.tsx` | 行点击跳转、hover 菜单、阶段/类型徽章 |
| `src/features/project-type/__tests__/ReferenceManager.test.tsx` | 保留 testid，补中文文案与空态按钮 |
| `src/pages/governance/__tests__/GovernanceShell.test.tsx`（及 legacy） | Tab 标签、头部 CTA、章节渲染 |
| `src/pages/governance/sections/__tests__/OverviewSection.test.tsx` | 下一步卡优先级（含阶段检测横幅）、里程碑折叠、Git 状态位于折叠区 |
| `src/pages/governance/sections/__tests__/SettingsSection.test.tsx` | 默认不自动请求 bootstrap suggest；高级折叠 |
| `src/pages/governance/sections/__tests__/KnowledgeSection.test.tsx` | 资料章只渲染入库/列表；语义检索默认折叠；Git 状态不在资料页 |
| `src/features/rules/__tests__/rulesView.test.ts` | `sourceDetail()` 单元测试（路径/非路径/全局层） |
| `src/features/rules/__tests__/RulesPanel.test.tsx`（新建或扩充） | 来源路径只显示文件名、冲突 tooltip、按钮文案 |

## 5. 实施步骤

- [x] **M1 · `/projects` 单列表重做**（纯前端）
  - 重写 `ProjectsOverview`；提取 `ProjectRow`；删除底部重复列表；批量模式；空态
  - 修复左栏启动竞态与 `/projects` 下重复入口
  - 验收：页面只有一份项目列表；无大块空白；搜索/筛选/排序/归档可用
- [x] **M2 · 概览章重组**
  - StatusCard 压缩；新增 NextActionsCard；里程碑简化；Playbook 操作收敛；项目结构折叠
  - 验收：默认可见按钮 ≤ 8 个；主 CTA 唯一；所有原能力可通过「查看全部 / ···」到达
- [x] **M3 · 设置章重组 + 去自动 LLM**
  - 五分区；SAGE.md 对话框化；`ProjectBootstrapPanel` 默认手动触发；术语替换
  - 验收：打开设置页无网络/LLM 请求；每个分区单一保存动作；无英文与内部术语
- [x] **M4 · 文件章 i18n**
  - 新增 `governanceFiles` 字典（zh + en 双文件 + 聚合器接入）；`ReferenceManager` 全量替换为 `t('governance.files.*')`；确认对话框同步本地化
  - 验收：中文界面下无英文残留；英文界面正常回退；ReferenceManager 全部 data-testid 保留
- [x] **M6 · 资料章重组 + 语义检索折叠**
  - 资料页只保留入库与列表；拆出 `SemanticSearchPanel` 并默认折叠；Git 状态移入概览折叠区；Wiki 生成移入设置高级区；术语中文化
  - 验收：资料页无 `M4`/`Embedder`/「语料池」等内部术语；Git 状态不在资料页；`StudioMaterialsAndProfilePanels.tsx` < 400 行
- [x] **M7 · 规则页文案收敛**
  - 来源路径显示文件名（tooltip 全路径）；冲突 tooltip；「查看规则生效顺序」
  - 验收：规则页功能与数据不变，仅文案/显示层差异
- [ ] **M5 · 壳层视觉统一 + 回归**（最后执行，覆盖 M1–M7 全部页面）
  - 下划线 Tab、去外层 Card、统一 Select/Button；跑 Vitest + `tsc` + 架构棘轮
  - 验收：CI 全绿；`architecture-baseline.json` 行数棘轮不新增超限文件

## 6. 测试计划

- Vitest：上述 8 个测试文件；覆盖率沿用 80% 门槛。
- `npm run build` + `tsc --noEmit`（CI `Frontend (TypeScript)` job）。
- 手工验收（Electron 真机）：
  1. 打开 `/projects`：仅一份列表，hover 出现次级操作，批量模式可用。
  2. 进入任一项目概览：默认仅见状态、下一步、里程碑；点「查看全部」能看到全部里程碑与操作。
  3. 打开设置：无自动分析请求；编辑 SAGE.md 通过对话框；高级区默认折叠。
  4. 文件章：全中文；添加/删除/重新扫描正常。
  5. 冷启动时左栏项目区最终能显示项目（不再永久空态）。
  6. 资料章：只有添加资料与资料列表；语义检索默认折叠；Git 状态不在本页。
  7. 规则章：来源路径显示 `SAGE.md`；冲突数有解释 tooltip；按钮文案已口语化。
- 截图对比：改造前 `/tmp/shot-*.png`（本方案采集）与改造后同页面。

## 7. 风险与依赖

| 风险 | 缓解 |
|---|---|
| 概览/设置大量组件移动导致测试快照失败 | 按里程碑分批更新断言；保留常用 testid |
| 删除底部 `WorkbenchProjectList` 影响既有入口 | 行组件抽成 `ProjectRow`，能力等价迁移（打开/新建会话/菜单/拖放注册） |
| 左栏隐藏「项目」分区引发现有测试失败 | 仅在 `/projects` 路由隐藏；其他路由行为不变 |
| 下划线 Tab 改动影响深链测试 | 保留 `data-testid="governance-tab-*"` 与 `tab` 参数解析逻辑不变 |
| i18n 键类型（`TranslationKey`）编译失败 | 先加 zh 字典（类型源），再加 en；运行 `tsc` 校验 |
| `StudioMaterialsAndProfilePanels.tsx`（785 行）拆分影响资料面板测试 | 先纯移动抽 `SemanticSearchPanel`，再改资料区；保留 `data-testid` |
| 资料页移出 Git/Wiki 后入口丢失 | 概览折叠区与设置高级区保留等价入口，验收时逐项核对 |
| 双分支同步 | 纯前端改动，逐里程碑 cherry-pick 到 `release/win7`；冲突点预计在 i18n 聚合文件与 `ProjectsOverview.tsx`，按 win7 分支实际行号重应用 |

## 8. 验收标准

- [ ] `/projects` 页面只有一份项目列表，无异常空白；一屏完成查找与打开
- [ ] 左栏不再出现与主区重复且状态不一致的项目入口
- [ ] 概览页默认可见操作 ≤ 8 个，原能力均可通过渐进披露到达
- [ ] 设置页打开时不自动触发 LLM；术语全部口语化
- [ ] 文件章中文完整，无英文残留
- [ ] 资料章只见「添加资料 + 资料列表」；语义检索默认折叠；Git 状态不在资料页；无 `M4`/`Embedder`/「语料池」等内部术语
- [ ] 规则章来源路径只显示文件名，按钮文案口语化，功能无回归
- [ ] Vitest / tsc / 架构棘轮全绿
- [ ] release/win7 同步完成

## 9. 归档

实施完成后：功能点并入 `docs/technical/`（项目工作台 IA 与交互）与 `docs/user-manual/`（项目管理操作），随后删除本计划文档。
