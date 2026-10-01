# UX-IA Round 3：侧栏槽位统一（Panel Slot）—— 方案 + 批次 0/A

> 日期：2026-10-01 · 基线：`origin/main` @ `419ff871f`（#1866）
> 工作分支：`feat/auto-20261001-e284d446`（worktree `.worktrees/feat-auto-20261001-e284d446`）
> 对标：Codex、ChatGPT、Claude、Cursor 的左栏/右面板布局惯例
> 前置阅读：`DESIGN.md`、`docs/plans/2026-09-29_ux-ia-round1.md`（§1.1 信息架构）、
> `docs/plans/2026-09-18_right-panel-r1-plan.md` ~ `r4`、`docs/plans/parity-loop-sop.md`

---

## 0. 结论速览

| 问题 | 结论 |
| --- | --- |
| 核心问题 | 不是功能多，是**侧边槽位没有所有者**：左栏一列叠了「导航 + 6 个内容分组 + 页脚」三层滚动区；右栏存在 chat / wiki / ModelCatalog / TaskCenter **四套并存的实现**，状态分散在 ~9 个 localStorage 键，无互斥无注册表 |
| 主流做法（共同点） | ① 左 = icon rail（作用域）+ 内容列（**同一时刻一个列表**）；② 右 = **一个 slot 一个宿主**，谁能占、能否共存由注册表声明；③ 提醒**只有一层**，折叠态仍带角标 |
| 本轮交付 | 批次 0 小修（去重复入口 / 去占位 / 去死代码 / nav 去重 / rail 补角标）+ 批次 A 地基（`PanelShell` + `panelRegistry` + `usePanelStore`） |
| 暂缓 | 批次 C（右栏迁 PanelShell）**等 #1828 合并**；批次 B 走独立 PR（涉 17 个既有测试） |
| 双分支 | 纯前端零新依赖，main 落地后 cherry-pick `release/win7`；回填 §7 交付号 |

---

## 1. 现状体检

### 1.1 左栏：一列三层滚动 + 入口重复

`src/widgets/layout/Sidebar.tsx` 竖向叠了五段：

| 段 | 位置 | 问题 |
| --- | --- | --- |
| 品牌栏 48px | `:372` | — |
| 主操作条（新建对话 / 搜索） | `:389-412` | — |
| nav `overflow-y-auto` | `:415` | 自身是一个滚动容器 |
| └ 3 个一级项 + 「更多」6 项 | `:416-493` | 导航与内容同级，视觉无区分 |
| └ 6 个可折叠 section | `:496-498` | 每个 section **内部再各自滚动** |
| 页脚（LiveDot / 版本 / 齿轮） | `:502-536` | 设置入口第 4 份实现 |

**G1 嵌套滚动 3 层**：nav 自带滚动（`:415`）+ `ConversationsSection` 两处 `maxHeight="50vh"`（`:174`、`:266`）+ `ProjectSection` `maxHeight="30vh"`（`:747`）。滚到子列表底部才轮到外层，跟手感差。

**G2 导航与内容同列**：9 个路由链接 + 6 个内容分组共享一列，读起来是 15 项平铺列表，缺少「导航 / 内容」层级。

**G3 入口重复**：左栏 `TodoSection` 只是「预览前 5 条 + 跳转」（`sections/TodoSection.tsx:38` → `/todos`），而 `App.tsx` 有完整 `TodoPage` 路由；`CronJobSection.tsx:33` → `/scheduled` 同理。同一功能两个入口。

**G4 占位分组**：`TeamSection` 渲染「占位 - 团队协作将在 Phase 6 接入」，无功能却长期占位。

**G5 死代码**：`UsageStatsSection` / `WorkspaceInfoSection` 在 `widgets/sidebar/index.ts` 导出，全仓零引用（barrel 导出让 knip 看不见）。

**G6 nav 渲染三份拷贝**：rail（`:323-351`）、primary（`:416-444`）、more（`:466-491`）各写一遍 isActive / featureKey / 图标 / Link，且细节已漂移——rail 有 Tooltip + aria，primary 有 AttnBadge，more 两样都没有；设置项又在页脚单独写第四遍（`:520-535`）。

**G7 折叠态丢提醒**：`AttnBadge` 只在展开态「对话」（`:441`）与页脚错误（`:517`）渲染；56px rail 全部丢失，待处理审批 / 新产物红点在折叠时不可见。

### 1.2 右栏：四套实现、三种视觉语言

| 实现 | 位置 | 形态 |
| --- | --- | --- |
| chat RightPanel | `widgets/chat/RightPanel.tsx` | 5 tab（`:55-61`）+ 铃铛 + S/M/L 三档（`w-5 py-0.5 text-[10px]`，20px 点击区）+ 最大化 + 关闭全挤在一行（`:197-202`） |
| wiki RightPanel | `widgets/wiki/RightPanel.tsx` | 独立第二实现，头部样式不同（`uppercase tracking-wide`）、无 tab、垂直二分「预览 / 深度研究」 |
| ModelCatalog 内联栏 | `pages/ModelCatalog.tsx` | 第三种：`w-96` / `w-[480px]` 硬编码 |
| TaskCenterWidget | `TaskCenterWidget.tsx:305` | `fixed bottom-4 right-4 z-40` 常驻浮层，**正好压在右栏右下角** |

外加 `TerminalPanel`（自带 store + 高度持久化）与 `DeliveryDrawerHost`（全局抽屉）。

**G8 持久化键散成 ~9 个**：`right-panel-open` / `-tab` / `-width` / `-auto-open`、`terminal-panel-open` / `-height`、sidebar width、sider sections（order + collapsed）、`more-open`。无注册表、无重置、**无互斥联动**——开终端不收右栏，右栏最大化后 TaskCenter 浮层仍在最上层。

**G9 右栏不是 app 级概念**：只有 Chat 有右栏，`/memory` `/office` `/skills` 都没有。`RightPanel` 在 `Chat.tsx:1219` 内挂载。

### 1.3 与并行会话的关系（重要）

`#1869`（`feat/auto-20261001-8cda8224`）同日提交了同主题文档
`docs/plans/2026-10-01_mainstream-ai-ux-optimization-proposal.md`，诊断是
「不缺功能，缺价值闭环」，批次 P0-1~P0-6 已落地。

**分工**（互补不重复）：

| 维度 | #1869 | 本文 |
| --- | --- | --- |
| 主张 | 把**已建成能力接到用户手上**（记忆删除、Office 修复、审批回执） | 给**侧边槽位建统一宿主**（布局架构） |
| 重叠点 | IA3 进度两处并存 ↔ 本文 G9/G8；P1-5 记忆/知识库入口收敛 ↔ 本文 §3 批次 B；P1-7 隐藏功能发现路径 ↔ feature-unlock 机制 | 明确分工：#1869 管**路由级心智模型**，本文管**布局级槽位** |
| 冲突面 | 占用 `Chat.tsx` / `Message.tsx` / `MessageList.tsx` / `TurnGroup.tsx` / `MemoryBrowser.tsx` / `Settings.tsx` | 本轮只碰 `Sidebar.tsx` / `widgets/sidebar/` / 新增文件 |

---

## 2. 并行冲突登记（决定批次顺序）

开工前按 `AGENTS.md` 原则 2 核对在飞 PR 的占用文件：

| PR | 占用文件 | 对本文影响 |
| --- | --- | --- |
| **#1828** 模型轨迹查看器 | `widgets/chat/RightPanel.tsx`、`features/right-panel/rightPanelStore.ts`、`widgets/chat/TrajectoryPane.tsx` | **批次 C 阻塞**——右栏两个核心文件正在被改，等合并后重做 |
| **#1133** 桌宠 P1 | `widgets/layout/Layout.tsx` | 批次 B 的容器改动需等其合并 |
| **#1867 / #1868** 产品路线批次 A/B | `widgets/layout/Sidebar.tsx`、`widgets/layout/__tests__/Sidebar.feature-unlock.test.tsx`、`widgets/sidebar/sections/ProjectSection.tsx` | **批次 B 阻塞**（与本 PR 自身也冲突，见下）；本 PR 的 `navItems` 改动与它们的 `primaryNavItems` / `moreNavItems` 落在同一片字面量上 |
| **#1869** 价值闭环 | `Chat.tsx` / `Message*.tsx` / `MemoryBrowser.tsx` / `Settings.tsx`、`widgets/sidebar/sections/ConversationsSection.tsx` | 批次 B-2（项目→会话合并树）涉 `ConversationsSection`，需等其合并 |
| **#1334** 投递三通道 | `widgets/task-center/__tests__/*` | 批次 C 的 TaskCenter 改造需等其合并 |

**批次 B 的入口当前被全部占用**（`Sidebar.tsx` ← #1867/#1868，`Layout.tsx` ← #1133，`ConversationsSection.tsx` ← #1869，`ProjectSection.tsx` ← #1867/#1868），故本轮未实施。解阻路径见 §8。

### 2.1 本 PR 自身与 #1867 / #1868 的重叠

| 位置 | 本 PR（批次 0） | #1867 / #1868 |
| --- | --- | --- |
| `primaryNavItems` | 插入 `待办`（`/todos`） | 插入 `项目工作台`（`/projects`）、`文档与验收`（`/office`） |
| `moreNavItems` | 插入 `定时任务`（`/scheduled`） | 移除 `Office` |
| `ADVANCED_FEATURE_BY_PATH` | 不动 | 移除 `'/office'` 门控 |
| import 区 | 移除已删分组的引用 | 新增 `Folder` 图标、`isEndpointConfigured` |

两侧都改同一批 `navItems` 字面量，合并必冲突。**建议产品路线先合并、本 PR rebase**：本分支只有 2 个提交且改动集中在导航项定义与分组渲染，且无三方语义冲突（待办/定时是一级导航项、项目工作台是另一条产品线入口，可共存）。已在 #1870 留言同步。

---

## 3. 方案：四批次

### 批次 0 —— 小修（不改架构，独立可回滚）

| # | 项 | 文件 | 做法 |
| --- | --- | --- | --- |
| 0-1 | 删占位分组 | `Sidebar.tsx`、`widgets/sidebar/sections/TeamSection.tsx`、`widgets/sidebar/index.ts` | `TeamSection` 零功能且明确写着 Phase 6 才接入；未接入前不占左栏位置。删文件 + 从 `SECTION_KEYS` 移除。`useSiderSections` 读存量时按 `defaultOrder` 过滤，残留 `team` 自动丢弃，无需迁移脚本 |
| 0-2 | 删死代码 | `widgets/sidebar/index.ts`、`sections/UsageStatsSection.tsx`、`sections/WorkspaceInfoSection.tsx`、`src/shared/api/workspaceInfoApi.ts` | 前两者全仓零引用（barrel 导出使 knip 失明）。**连带发现**：`workspaceInfoApi.ts` 的唯一消费方就是 `WorkspaceInfoSection`，两者同在 #1621 提交中落地且出生即死，删分组后它成为 knip 新增违规，一并删除（后端 `backend/services/workspace_info.py` 保留，未来接 UI 时客户端可从 git 历史取回） |
| 0-3 | 消除重复入口 | `Sidebar.tsx`、`sections/TodoSection.tsx`、`sections/CronJobSection.tsx` | 待办 / 定时已有完整整页（`/todos`、`/scheduled`）。左栏分组只是「预览前 5 条 + 跳转」，与整页构成同一列里的两个同名标签。**降级为一级导航项**：「待办」升入一级（agent 产品的每日收件箱），「定时任务」留在「更多」（低频配置）。数据加载无影响 —— `useTodoStore.load()` / `useScheduledTaskStore.load()` 的另一调用方在各自整页内 |
| 0-4 | nav 渲染去重 | `src/widgets/layout/SidebarNavItem.tsx`（新）、`Sidebar.tsx` | 抽 `<SidebarNavItem item variant="rail" \| "row" trailing />`，三份拷贝合一，行为取并集：rail 与 row 都带 Tooltip + aria，都支持角标 |
| 0-5 | rail 补提醒 | `Sidebar.tsx` | collapsed 分支渲染 `AttnBadge`（复用 `attentionCount`），修 G7。此前用户一按 Ctrl+B，「还有 N 项等你处理」就完全不可见 |

**验收结果**：现有 `Sidebar.*.test.tsx`（7 个）保持绿，`sections-integration.test.tsx` 按「分组 key 集合」重写（原断言按标题文案，待办/定时降级为导航项后文案断言会产生歧义），新增折叠态角标回归 3 例（`Sidebar.attention.test.tsx`）。

### 批次 A —— PanelShell + 槽位注册表（本轮地基）

| # | 项 | 文件 | 做法 |
| --- | --- | --- | --- |
| A-1 | `PanelShell` | 新增 `src/shared/ui/PanelShell.tsx` | 统一外壳：`header`（title 或 tabs + actions 槽）+ 左边缘拖拽手柄 + 空态三件套。**Chromium 106 不支持 `grid-template-rows: 0fr↔1fr` 插值**，若后续加折叠动画需沿用 `SiderSection.tsx:52-68` 的 motion 测高写法。开合动画不在本组件职责内（push/overlay 语义不同，由宿主处理） |
| A-2 | `panelRegistry` | 新增 `src/features/app-panels/panelRegistry.ts` | 声明式登记 9 个侧边面：`{ id, slot, label, migrationBatch, currentOwner }`；槽位几何表 `PANEL_SLOTS`（互斥/轴向/尺寸边界/是否可最大化）。尺寸边界取自现状（`useResizablePanel` 的 280~600、`terminalPanelStore` 的 120~600），迁移后用户可见行为不变 |
| A-3 | `usePanelStore` | 新增 `src/features/app-panels/usePanelStore.ts` | 每槽位 `{ open, active, size, maximized }`；持久化统一到 `sage:panels:v1`，**一次性迁移 5 个旧键后删除旧键**；两条互斥规则下沉到 store：同槽位互斥（activate 自动接管）、最大化独占（任一面最大化时清除其它槽位最大化态 —— 此前 `TaskCenterWidget` 以 z-40 压住最大化右栏就是缺这条规则的后果）。localStorage 不可用时静默降级到内存态 |
| A-4 | 接线范围 | —— | 本批次**只落地数据层与外壳组件，不迁移任何现有面板**。`RightPanel.tsx` / `rightPanelStore.ts` 正被 #1828 占用，按原则 2 不得并发编辑 |

**A-3 实现中被测试抓出的真 bug**：初版 `loadInitialState()` 迁移后**没有写回新键**，而 `migrateLegacy()` 已经删掉旧键 —— 用户若在迁移后直接关窗，面板尺寸永久丢失（迁移从"搬迁"退化为"破坏性操作"）。已修复并加回归用例（`从旧键迁移开合与尺寸，并删除旧键`）。

### 批次 B —— 左栏两段式（rail + 单列表内容列）

| # | 项 | 做法 |
| --- | --- | --- |
| B-1 | rail / 内容列拆分 | 56px rail 只放作用域（对话 / 记忆 / 知识库 / 自定义）+ 底部（设置 / 帮助 / 状态）；240px 内容列**同一时刻只渲染一个列表** |
| B-2 | 项目 → 会话合并树 | R1 §1.1 已提，一直未做。`ProjectSection` 与 `ConversationsSection` 合成一棵树，未归属会话进「最近」 |
| B-3 | 单滚动容器 | 去掉各 section 的 `maxHeight` 内滚，统一由内容列滚（修 G1） |
| B-4 | 导航/内容视觉分层 | rail 与内容列之间加明确分隔；导航项与内容项用不同字重与间距 |

**风险**：涉 17 个锁定当前行为的测试（`Sidebar.*.test.tsx` 7 + `widgets/sidebar` 10）。走独立 PR，测试同步改，不与批次 0/A 混提。

### 批次 C —— 右栏收成单槽位（**阻塞：等 #1828 合并**）

| # | 项 | 做法 |
| --- | --- | --- |
| C-1 | 三套右栏迁 `PanelShell` | chat / wiki / ModelCatalog 全部迁入，右栏升为 app 级 slot（`/memory`、`/office` 可用） |
| C-2 | 头部瘦身 | 5 tab 保留，铃铛 + 三档 + 最大化 + 关闭收进 `⋯` 溢出菜单；点击热区 ≥28px（现为 20px） |
| C-3 | TaskCenter 收进注册表 | 浮层不再以 z-40 压右栏（`TaskCenterWidget.tsx:305`） |

**阻塞原因**：#1828 正在改 `RightPanel.tsx` + `rightPanelStore.ts`，按 `AGENTS.md` 原则 2（单一所有者）不得并发编辑同文件。

### 批次 D —— 统一注意力层

一个 `AttentionCenter` 汇总审批 / 提问 / 新产物 / git dirty / todo / 连接失败，总数徽标固定在 rail 底部账户行。

**数据层已落地**（#1871，从 `origin/main` 独立切出，只新增 `src/features/attention/**`）：

| 文件 | 内容 |
| --- | --- |
| `attentionCenter.ts` | 纯函数聚合，按风险顺序（审批 > 提问 > 产物 > 待办 > 改动）输出单一快照 |
| `useAttentionSnapshot.ts` | 订阅层，接 permission / question / todo / changesList 四个 store |

三个设计决定：① **只读不加载**（不调 `load()`，否则把侧栏重新绑回数据加载）；② **选择器返回原始值**（返回 number 而非新对象，避免 zustand 死循环）；③ **刻意不含定时任务**（现有 store 无到期判定，"已启用数" ≠ "需要你处理"，不发明语义）。

**UI 接线**（rail 总数角标 + 汇总气泡）随批次 B 一起做，届时本模块是唯一取数来源。

---

## 4. 设计原则（写进代码注释，防回退）

1. **一个槽位一个宿主**：任何新面板必须先在 `panelRegistry` 登记，不得新起一套 store + localStorage。
2. **持久化只有一个命名空间**：`sage:panels:v1`。新面板禁止自造 `xxx-open` / `xxx-width` 键。
3. **互斥用数据声明**：谁能同时开写在 registry，不写在组件的 `useEffect` 里。
4. **点击热区下限 28px**，图标按钮必须带 Tooltip 或 `aria-label`。
5. **折叠态不得丢信息**：rail 上任何被折叠隐藏的状态，都要有等价角标。

---

## 5. 本轮验证命令与结果

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 前端测试（定向） | `npx vitest run src/widgets/sidebar src/widgets/layout src/features/app-panels src/shared/ui` | 绿（新增 30+ 例） |
| 前端测试（全量） | `npx vitest run` | 465 文件：463 通过 / 2 跳过 |
| 类型检查 | `npm run typecheck` | 通过 |
| 架构基线 | `node scripts/architecture-check.mjs` | 通过（72 基线项，800 行上限；`Sidebar.tsx` 540 → 479 行） |
| 死代码（棘轮） | `npm run knip` | 未使用导出 **134 → 129**（净减 5）；未使用文件 13 → 13（删 `workspaceInfoApi.ts` 补回 `WorkspaceInfoSection` 造成的增量）；本批次新增文件零违规 |

> 棘轮要求"只增不减"。`PanelShell` 的 props 类型与 `panelRegistry` 的数据表一度被 knip 判为新增未使用导出，处理方式是**让测试直接消费它们**（注册表内容本就该被断言），而不是往基线里加条目。

## 6. 明确不做

| 项 | 理由 |
| --- | --- |
| 会话拖拽排序 | 后端 SQL 排序（`Sidebar.tsx` 注释段）有明确产品理由 |
| 放宽设计密度 | `DESIGN.md` 的 calm/dense 是主动选择（#1869 §8 同结论） |
| 记忆/知识库路由合并 | 属 #1869 的 P1-5，本轮只做布局层，路由心智模型归他们 |
| 批次 C 抢跑 | #1828 未合并，违反单一所有者原则 |
| 本轮不提交/推送 | 按 AGENTS.md 原则 4，CI 才是权威门禁；由用户决定何时开 PR |

## 7. 交付号回填

| 批次 | main PR | win7 PR | 状态 |
| --- | --- | --- | --- |
| 方案文档 | **#1870** | 待回填 | CI 全绿（14 pass / 2 skip） |
| 批次 0 | **#1870** | 待回填 | 已实现，CI 全绿 |
| 批次 A | **#1870** | 待回填 | 已实现，CI 全绿（未接任何现有面板） |
| 批次 D 数据层 | **#1871** | 待回填 | 已实现，CI 全绿（14 pass / 2 skip） |
| 批次 B | — | — | **阻塞**：入口文件被 #1867/#1868/#1133/#1869 占用 |
| 批次 C | — | — | 阻塞于 #1828（占 `RightPanel.tsx` + `rightPanelStore.ts`） |
| 批次 D UI 接线 | — | — | 依赖批次 B 的 rail 位置 |

### 7.1 #1871 的 CI 红灯与处置（2026-10-01）

首次运行的 `Electron smoke (playwright-electron)` 失败，但**失败点不在冒烟测试**：

```
#4 Install npm dependencies  -> failure
#5 Build frontend + Electron -> skipped
#6 Smoke test                 -> skipped
```

日志根因：`npm error RequestError: connect ETIMEDOUT 172.182.252.133:443`，
来自 electron 的 postinstall（`node install.js`）从 GitHub CDN 拉二进制超时 ——
runner 出网问题，与代码无关（本分支零 `package.json` 改动，只新增 5 个文件）。
用 `POST /actions/runs/<id>/rerun-failed-jobs` 只重跑该 job 后全绿。

**排查时的坑**：同一时段 `gh` CLI 的 GraphQL 与 REST 请求在我这边全部返回
`EOF`，但 `Invoke-RestMethod` 直连 `api.github.com` 正常（HTTP 200）。
CI 状态复查因此改走 REST + `Invoke-RestMethod`，不再依赖 `gh`。
若后续再遇到 `Electron smoke` 红灯，**先看失败的是第几步**：
第 4 步 = 依赖安装（网络/registry），第 6 步 = 真正的冒烟失败（才需要查代码）。

## 8. 批次 B 的解阻路径

批次 B（左栏两段式 = rail 常驻 + 单列表内容列 + 单滚动容器）是**用户可感知的收益**，但四个入口文件当前全被占用。按依赖顺序：

```
1. #1867 / #1868 合并（产品路线）  ─┐
2. 本 PR #1870 rebase 后合并        ─┴─→  #1869 合并  →  #1133 合并
                                                          ↓
                                            批次 B 可开工（Sidebar / Layout / ConversationsSection / ProjectSection 均空闲）
                                                          ↓
                                            批次 D UI 接线（rail 总数角标）
```

批次 B 的实施要点（供开工时直接用）：

- **总量不变**：rail 固定 56px，内容列吃剩余宽度 → `Layout.tsx` 只需把 `width` 语义从"整栏宽"改为"内容列宽"，或让 `Sidebar` 内部拆分。`useResizableSidebar` 的 min 220 会让内容列只剩 164px，建议同步调到 260~480。
- **`collapsed` 语义变为"隐藏内容列"**：折叠态的 rail 就是现有的 `Sidebar collapsed` 实现，可直接复用，不需要新组件。
- **测试影响面**：`Sidebar.*.test.tsx` 7 个 + `widgets/sidebar` 10 个。其中 `sidebar-settings-link`（移入 rail 底部）、`sidebar-version`、`sidebar-new-chat-primary`、`sidebar-search-button` 的 testid 与语义必须保持；`Sidebar.more-group.test.tsx` 大概率要删（rail 消除了「更多」分组的存在理由）。
