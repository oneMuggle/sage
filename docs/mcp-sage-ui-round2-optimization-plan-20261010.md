# Sage UI 深度优化建议方案（第二轮 · Post-#1927 新基线）

> **基线版本**：`origin/main` @ `66fb6e5f2` / `origin/release/win7` @ `a4c43d9dd`（2026-10-10，已完成第一轮 `UI-P0` ~ `UI-P2` 共 10 项改造合入）
> **已收口成果回顾（不再重复立项）**：
> - 对话页顶栏 `ChatHeaderBar.tsx` 已收编 5 项会话控件（模型选择、权限档位、上下文水位、编排模式、新话题），底部 `InputCard.tsx` 已精简为纯单行输入框；
> - 全仓 11 个组件的 34 处原生 `window.alert/confirm/prompt` 已 100% 清零；
> - `Titlebar` 双 Logo 去重、移动端 `<768px` 底栏扩容、右栏 6-Tab 紧凑化、弹窗 `Escape`/`aria-modal` 已落地；
> - Top 13 组件硬编码色值已迁移，`font-scale-baseline.json` 已从 183 压降至 **109 处**（`main`）/ **117 处**（`win7`）；
> - `Chat.tsx`（643 行）、`Message.tsx`（657 行）、`OfficeEditPreviewDialog.tsx`（778 行）已全部拆解至 `< 800` 行并永久退出 `architecture-baseline.json`。

---

## 一、第二轮 UI 深度诊断总览（8 大进阶优化方向）

在第一轮解决「底部发送区拥挤、原生阻塞弹窗、三大巨型组件超限」之后，围绕 **中等窗口分栏挤压、多智能体运行时底部面板堆叠、阅读流体验、设置中心信息架构、存量色板/字号长尾治理、剩余 4 个超大 UI 文件拆解** 六大维度，梳理出以下 **8 项高 ROI 的 UI 进阶优化建议**：

| 优先级 | 编号 | 优化模块 | 核心痛点（Post-#1927 现状） | 预期收益 |
|---|---|---|---|---|
| **P0** | **UI-R2-P0-1** | **对话页顶栏（`ChatHeaderBar`）自适应折叠与按钮去重** | 顶栏右侧塞入 8 个交互控件（`~620px`），当左栏（`260px`）+ 右栏（`320–480px`）同时展开时，中间对话列仅宽 `580–740px`，会话标题被挤压至消失，且顶栏「+ 新对话」与左栏「新建对话」重复且与「新话题」混淆 | 任意分栏宽度下顶栏零溢出、标题始终可读；消除「新话题 vs 新对话」认知混淆 |
| **P0** | **UI-R2-P0-2** | **对话底部动态状态栈（Activity Tray）手风琴互斥收口** | `MessageList` 与 `ChatInput` 之间在运行时最多同时堆叠 `ChatPlanStrip` + `SubagentLivePanel` + `PendingQueueStrip` + `TerminalPanel` 共 4~5 层面板，1366×768 / 1440×900 屏幕下消息滚动区被挤压至 `< 180px` | 底部动态状态聚合为单行 `32px` 活动托盘，展开详情实行手风琴互斥，释放 **150px–240px** 对话可视高度 |
| **P0** | **UI-R2-P0-3** | **消息流阅读体验精修（代码块吸顶栏 + 连续工具调用聚合 + 表格增强）** | ① 长代码块滚到中部时无法复制（顶部栏滚出视口）；② Agent 连续调用 8~15 次工具时产生一长串独立卡片打断阅读；③ 宽 Markdown 表格横向撑破布局且无法一键复制 | 长代码随处一键复制/切换换行；连续已完成工具调用自动聚合成单行可展开时间线；表格支持滚动阴影与一键复制 TSV |
| **P1** | **UI-R2-P1-1** | **设置中心（`Settings.tsx`）分域侧栏导航 + 搜索过滤 + 消灭亮白原生 `<select>`** | 12+ 个设置 Tab 平铺缺乏分类与搜索定位；多处使用原生 `<select>`，在 Windows 暗色模式下点击弹出刺眼系统白底菜单；各 Tab 卡片间距与保存反馈不统一 | 3 大分组侧栏 + 顶部即时搜索秒级定位设置项；自定义主题化 `<Select>` 彻底消除暗色模式白底原生下拉框 |
| **P1** | **UI-R2-P1-2** | **三套右侧面板（`chat` / `wiki` / `ModelCatalog`）统一迁入 `PanelShell`** | 对话右栏、Wiki 右栏、模型目录详情栏各自维护拖拽宽度、头部高度（`h-10` vs `h-12`）与关闭逻辑，跨页面切换时右栏宽度与分割线跳动 | 全站右栏统一 `h-12` 头部基准线、统一拖拽高亮手柄、`S/M/L` 档位记忆与 `Escape` 退让 |
| **P1** | **UI-R2-P1-3** | **动态字号二期（`109 → <25` 处）与长尾硬编码色值清零** | `font-scale-baseline.json` 仍余 **109 处**（66 个文件）；`OfficeDeliveryDrawer`、`ProjectTypeBadge`、`ProjectTypeSelector`、`ArenaPage`、`ModelCatalog` 仍残留 `~340 处` 亮色 Tailwind 调色板 | 用户调节字号时全站 98%+ 文字同步缩放；Office/项目/竞技场在暗色与暖色主题下色彩完全语义化 |
| **P2** | **UI-R2-P2-1** | **前端剩余 4 个超 800 行 UI 巨型组件拆解并退出架构基线** | `OfficePreviewPanel.tsx`（1,081 行）、`NetworkTab.tsx`（1,001 行）、`ProjectSection.tsx`（923 行）、`ProjectWorkspace.tsx` / `ArenaPage.tsx`（~900 行）仍滞留 `architecture-baseline.json` | 前端 `src/` 目录超 800 行历史豁免文件清零，单文件职责清晰、降低 PR 冲突率 |
| **P2** | **UI-R2-P2-2** | **全站二级页面顶栏对齐（`PageHeader`）与统一空状态/骨架屏规范** | `Tasks` / `Knowledge` / `Wiki` / `Skills` / `Arena` 顶栏高度不一，与左栏 `Sidebar` 顶部 `h-12` 分割线错位；加载态多为纯文本 `"加载中..."` | 全应用所有页面顶栏 `h-12` 分割线像素级贯通；切换页面零布局跳动（CLS），空状态具备统一插画与 CTA 引导 |

---

## 二、逐项深度分析与具体设计方案

### 2.1 【UI-R2-P0-1】对话页顶栏（`ChatHeaderBar.tsx`）响应式分级折叠与按钮精简

#### 现状与痛点
- 第一轮将 5 项会话控件移入 `src/pages/chat/ChatHeaderBar.tsx` 后，顶栏右侧 `data-testid="chat-header-controls"` 加上原有的顶栏按钮共包含 **8 个水平排列项**：
  1. `SessionModelPicker`（模型选择器，约 `160px–220px`）
  2. `PermissionModeSwitch`（权限开关 + 自动批准计数，约 `95px–150px`）
  3. `ContextMeter`（进度条 + 百分比 + 告警态，约 `85px–120px`）
  4. `orch-mode-select`（编排模式胶囊，约 `88px`）
  5. `chat-new-topic`（`+ 新话题`，约 `76px`）
  6. `RightPanel` 展开/收起按钮（`32px`）
  7. `+ 新对话` 按钮（约 `76px`）
  8. `⋯` 更多操作菜单（导出 Markdown/PDF、记忆面板等，`32px`）
- **问题 1（中等窗口分栏挤压）**：当用户在 `1440px` 屏幕上同时打开左栏（`260px`）与右侧工作台（`420px`）时，中间对话列宽度仅 `760px`。右侧 8 个控件占去 `~640px`，导致左侧会话标题与项目徽标被挤压至不足 `100px`（仅能显示 `2~3` 个汉字加省略号 `...`）。
- **问题 2（「新话题」与「新对话」并列造成认知混淆）**：左栏顶部已有显眼的「新建对话 (`Ctrl+N`)」主按钮，而对话顶栏右侧同时并排出现「新话题」与「新对话」两个带加号的按钮，不仅占用 `150px+` 宽度，且用户极易点错。

#### 优化方案
1. **精简顶栏冗余「+ 新对话」按钮**：
   - 当左侧栏处于展开状态时，隐藏对话顶栏右侧重复的「+ 新对话」文字按钮（保留在 `⋯` 更多菜单或左栏折叠时以紧凑图标展示），顶栏主操作明确聚焦于当前会话的「**新话题 (`chat-new-topic`)**」。
2. **引入两级响应式紧凑布局（Responsive Compact Pills）**：
   - 为对话主列容器标记 `@container/chat`（或结合窗口断点）：
   - **宽裕态（对话列宽 `≥ 820px`）**：完整展示图标 + 文案（当前形态）；
   - **紧凑态（对话列宽 `< 820px`，如右栏打开时）**：
     - `chat-new-topic` 自动隐藏文字标签，仅展示带 Tooltip 的 `MessageSquarePlus` 图标按钮（省 `48px`）；
     - `orch-mode-select` 在默认 `auto` 状态下折叠前缀标签，仅展示 `⚡ 自动 ▾` 紧凑胶囊（省 `44px`）；
     - `PermissionModeSwitch` 的自动批准计数徽标收拢为角标数字（省 `55px`）；
     - `SessionModelPicker` 最大宽度从 `max-w-[200px]` 自适应收缩至 `max-w-[140px]`，确保左侧会话标题始终保有 `≥ 180px` 的可读宽度。

---

### 2.2 【UI-R2-P0-2】对话主视口底部动态状态栈（Bottom Status Stack）手风琴互斥收口

#### 现状与痛点
- 在 `src/pages/Chat.tsx` 中，虽然底部 `ChatInput` 已成为单行，但在 `MessageList` 与 `ChatInput` 之间依次挂载了：
  - `ChatPlanStrip.tsx`（计划步骤条，展开时高 `120px–220px`）
  - `SubagentLivePanel.tsx`（子代理并行状态面板，展开时高 `100px–180px`）
  - `PendingQueueStrip.tsx`（待发送队列条，高 `40px–96px`）
  - `TerminalPanel.tsx`（终端面板，高 `200px–320px`）
- 当执行复杂多代理任务时，上述面板会**同时处于展开态**，在笔记本屏幕上把中间 `MessageList` 挤压成一条窄缝，且各面板外边距（`mx-4` vs `px-3` vs 全宽 `border-t`）不一致，形成杂乱的“千层饼”堆叠。

#### 优化方案
1. **构建统一 `ChatBottomActivityTray.tsx`（底部活动托盘）**：
   - 将 `ChatPlanStrip`、`SubagentLivePanel`、`PendingQueueStrip` 收拢进同一个与 `InputCard` 宽度对齐的圆角上附着容器（`rounded-t-xl border border-b-0 border-border bg-bg-subtle/90 backdrop-blur-sm`）。
   - **单行聚合摘要头（高 `32px`）**：当存在多个活动状态时，顶部显示分段状态胶囊：
     `[📋 执行计划 3/5 ▾]  [🤖 子代理 (2 运行中) ▾]  [⏳ 待发队列 (1) ▾]`
   - **手风琴互斥展开（Accordion Mode）**：同一时刻最多展开**一个**详情抽屉（点击另一个胶囊自动切换，再次点击收起为 `32px` 摘要行），最大展开高度限制为 `max-h-[28vh] overflow-y-auto`。
2. **终端打开时的智能退让**：
   - 当 `TerminalPanel` 打开时，自动将活动托盘切为折叠摘要态，保障 `MessageList` 消息主视口永远不少于窗口高度的 `50%`。

---

### 2.3 【UI-R2-P0-3】消息流阅读体验精修（代码块吸顶栏 + 连续工具调用聚合 + 表格增强）

#### 现状与痛点
1. **长代码块操作不便（`src/widgets/chat/MessageMarkdownBody.tsx`）**：
   - 代码块顶部的语言标识与「复制」按钮随代码块一起滚走。阅读 100 行代码时，用户必须滚回代码块顶部才能点击复制；且缺少「自动换行 / 横向滚动」切换开关。
2. **连续工具调用刷屏（`src/widgets/chat/Message.tsx`）**：
   - 当 Agent 在单轮回复中连续执行 6~15 个只读/检索工具（如 `read_file`、`search_files`、`web_search`）时，消息气泡内会纵向铺开十几张工具卡片，把最终的文字结论推到几屏之外。
3. **宽 Markdown 表格体验粗糙**：
   - 表格缺少水平滚动容器与表头固定，列数较多时直接撑宽气泡或导致文字严重折行，且无法一键复制表格数据到 Excel。

#### 优化方案
1. **代码块 Sticky Header + 换行切换**：
   - 为代码块头部添加 `sticky top-0 z-10 bg-bg-tertiary/95 backdrop-blur-sm border-b border-border/60`；
   - 右侧提供 `[自动换行]` 切换图标 + `[复制代码]` 按钮（带已复制 `✓` 状态反馈）。
2. **连续已完成工具调用自动聚合（Tool Call Group Accordion）**：
   - 当同一条消息内存在 **$\ge 3$ 个连续已完成（`status === 'completed'`）** 的工具调用块时，默认聚合渲染为一行紧凑时间线摘要：
     `⚡ 已完成 6 步工具调用（读取 4 个文件 · 搜索 2 次 · 耗时 1.8s） [展开明细 ▾]`
   - 若其中有任意工具处于 `running` 或 `error` 状态，则该项保持展开，确保异常与实时进度零隐藏。
3. **Markdown 表格增强容器**：
   - 外层包裹 `overflow-x-auto rounded-lg border border-border my-2`，右上角悬浮提供 `[复制表格]`（复制为 TSV，可直接粘贴进 Excel / 飞书表格）与 `[全屏预览]` 按钮。

---

### 2.4 【UI-R2-P1-1】设置中心（`Settings.tsx`）分域导航重构 + 全局搜索 + 主题化 `<Select>`

#### 现状与痛点
- `src/pages/Settings.tsx` 目前承载了 **12+ 个设置子页**，导航项平铺展示，缺少逻辑分组与关键词搜索；
- 设置页与多处配置面板大量使用原生 `<select className="...">`（全仓共 **30+ 处**原生 `<select>`），在 Windows 暗色主题下点击下拉框时，操作系统会渲染白底黑字的原生菜单，视觉割裂感极强；
- 各设置 Tab 内部的区块标题、边框圆角、描述文字层级不统一。

#### 优化方案
1. **左侧分域垂直导航 + 顶部设置搜索框**：
   - 将设置中心左栏按三大领域分组：
     - **模型与连接**：模型提供商 (`Providers`)、自定义端点 (`Endpoints`)、MCP 服务 (`MCP`)、网络与代理 (`Network`)
     - **界面与交互**：外观与字号 (`Theme & Font`)、提示词模板 (`Prompts`)、快捷键 (`Shortcuts`)
     - **记忆与环境**：长期记忆 (`Memory`)、运行时环境 (`Runtime Env`)、数据与诊断 (`System`)
   - 导航栏顶部增加 `🔍 搜索设置项...` 输入框，输入关键词（如“字号”、“代理”、“API”、“MCP”）即时高亮并过滤对应分组。
2. **提炼轻量主题化 `<Select>` 组件（`src/shared/ui/Select/Select.tsx`）**：
   - 基于现有 Radix/Popover 原语封装支持键盘导航（`↑/↓/Enter/Esc`）与主题变量的 `<Select>` 组件，替换设置中心与工作台中高频的原生 `<select>`，彻底消灭暗色模式下的白底系统下拉菜单。

---

### 2.5 【UI-R2-P1-2】三套右侧面板统一迁入 `PanelShell` 容器规范

#### 现状与痛点
- `src/widgets/chat/RightPanel.tsx`、`src/widgets/wiki/RightPanel.tsx`、`src/pages/ModelCatalog.tsx` 仍各自维护外层容器、宽度拖拽与顶栏高度，导致：
  - 对话页顶栏是 `h-12`（48px），而右栏顶栏高度与分割线在不同页面存在 `4px–8px` 错位；
  - 拖拽右栏边缘调宽时缺少统一的视觉高亮线（`hover:bg-primary/40`）。

#### 优化方案
- 将三套右栏的外壳统一收口至 `src/shared/ui/PanelShell.tsx`：
  - 统一顶栏高度为 `h-12`（与左栏 `Sidebar` 顶部及主页面 `Header` 的 `border-b` 形成一条贯穿全窗口的水平基准线）；
  - 统一左侧 `4px` 拖拽热区与激活态高亮指示条、统一 `S (320px) / M (440px) / L (580px)` 档位切换与 `Escape` 关闭行为。

---

### 2.6 【UI-R2-P1-3】动态字号二期（`109 → <25` 处）与长尾硬编码色值收口

#### 现状与痛点
- 第一轮将 `scripts/font-scale-baseline.json` 从 183 压降至 **109 处**，并清理了 Top 13 组件的硬编码色值；
- 剩余 **109 处 `text-[Npx]`** 与 **~340 处硬编码色值**集中在：
  - `src/features/office/OfficeDeliveryDrawer.tsx` & `OfficePreviewPanel.tsx`
  - `src/features/project-type/ProjectTypeBadge.tsx` & `ProjectTypeSelector.tsx`
  - `src/pages/ArenaPage.tsx` & `src/pages/ProjectWorkspace.tsx`
  - `src/widgets/sidebar/Sidebar.tsx` & `src/pages/settings/NetworkTab.tsx`

#### 优化方案
- 批量迁移上述组件的硬编码字号至 `text-ui-2xs` / `text-ui-xs` / `text-ui-sm`，执行 `node scripts/check-font-scale.mjs --tighten` 将全仓基线从 **109 处压降至 `< 25` 处**；
- 将 `ProjectTypeBadge`、`OfficeDeliveryDrawer`、`ArenaPage` 中的硬编码亮色徽标（如 `bg-amber-100 text-amber-800`、`bg-purple-100 text-purple-800`）统一替换为暗色友好的语义半透明令牌（`bg-warning/15 text-warning`、`bg-accent-soft text-accent`）。

---

### 2.7 【UI-R2-P2-1】拆解前端 `src/` 剩余 4 个超 800 行巨型组件并清零架构豁免

#### 现状与痛点
- 第一轮已将 `OfficeEditPreviewDialog.tsx`、`Chat.tsx`、`Message.tsx` 移出 `architecture-baseline.json`。
- 当前 `src/` 下仅剩最后 **4 个核心大组件**仍高于 800 行红线：
  1. `src/features/office/OfficePreviewPanel.tsx`（**1,081 行**）
  2. `src/pages/settings/NetworkTab.tsx`（**1,001 行 `main` / 990 行 `win7`**）
  3. `src/widgets/sidebar/sections/ProjectSection.tsx`（**923 行**）
  4. `src/pages/ProjectWorkspace.tsx` / `src/pages/ArenaPage.tsx`（**~884–906 行**）

#### 优化方案
- **`OfficePreviewPanel.tsx`** → 拆出 `OfficePreviewToolbar.tsx`、`OfficeSnapshotModal.tsx`、`OfficeFormatRenderer.tsx`，主文件降至 **`< 620` 行**；
- **`NetworkTab.tsx`** → 拆出 `ProxySettingsCard.tsx`、`ChannelHealthTable.tsx`、`NetworkDiagnosticCard.tsx`，主文件降至 **`< 450` 行**；
- **`ProjectSection.tsx`** → 拆出 `ProjectItemRow.tsx`、`ProjectContextMenu.tsx`，主文件降至 **`< 520` 行**；
- **`ProjectWorkspace.tsx` & `ArenaPage.tsx`** → 抽离头部与子面板组件，全部降至 **`< 700` 行**；
- 运行 `node scripts/architecture-check.mjs --tighten`，将上述组件全部从 `architecture-baseline.json` 中**永久移除**。

---

### 2.8 【UI-R2-P2-2】全站二级页面顶栏对齐（`PageHeader`）与统一空状态/骨架屏规范

#### 现状与痛点
- 从「对话 (`Chat`)」切换到「定时任务 (`ScheduledTasks`)」、「知识库 (`Knowledge`)」、「Wiki」、「技能 (`Skills`)」时，页面顶部标题栏高度、内边距与分割线位置不一致（有的无 `border-b`，有的高度为 `56px` 或 `64px`），与左侧栏顶部 `h-12`（48px）分割线产生明显错位；
- 列表首次加载时缺少骨架屏占位，空列表状态各页写法不一。

#### 优化方案
- 提炼共享 `<PageHeader icon title subtitle badge actions />` 组件（标准 `h-12 px-4 border-b border-border flex items-center justify-between`），在 `ScheduledTasks`、`Knowledge`、`Wiki`、`Skills`、`ArenaPage`、`Settings` 统一接入，实现**全站顶栏基准线 100% 像素级对齐**；
- 提炼共享 `<EmptyState />` 与 `<CardListSkeleton />` 组件，统一列表加载态与空状态视觉语言。

---

## 三、建议分批落地路线图（支持双轨 `main` + `release/win7` 零回归交付）

| 批次 | 包含任务 | 核心交付物 | 预计耗时 |
|---|---|---|---|
| **第一批（Batch 1 · P0 核心对话页精修）** | `UI-R2-P0-1` + `UI-R2-P0-2` + `UI-R2-P0-3` | ① `ChatHeaderBar` 窄宽自适应紧凑胶囊 + 去除重复「新对话」按钮；② 底部 `ChatBottomActivityTray` 手风琴互斥折叠（释放 150px+ 视口高度）；③ 代码块吸顶复制栏 + 连续工具调用自动聚合折叠 + Markdown 表格一键复制 | 1 个迭代批次 |
| **第二批（Batch 2 · P1 设置中心、右栏对齐与主题/字号二期）** | `UI-R2-P1-1` + `UI-R2-P1-2` + `UI-R2-P1-3` | ① 设置中心三大分组导航 + 即时搜索 + 主题化 `<Select>`；② 三套右栏统一 `h-12` 基准线与拖拽手柄；③ `font-scale-baseline.json` 从 `109 → <25` 处 & 剩余工作台组件暗色令牌对齐 | 1 个迭代批次 |
| **第三批（Batch 3 · P2 剩余超大组件清零与全站顶栏/空状态统一）** | `UI-R2-P2-1` + `UI-R2-P2-2` | ① `OfficePreviewPanel`、`NetworkTab`、`ProjectSection`、`ProjectWorkspace`/`ArenaPage` 全部拆降至 `<800` 行并退出 `architecture-baseline.json`；② 全站二级页面接入统一 `h-12 <PageHeader>` 与 `<EmptyState>` | 1 个迭代批次 |
