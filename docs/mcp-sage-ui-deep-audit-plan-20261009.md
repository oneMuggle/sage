# Sage UI 深度体检与系统化优化方案（2026-10-09）

> **基线版本**：`origin/main` @ `e3654b970` / `origin/release/win7` @ `8eb9c3fc3`（已完成 P0–P2 共 15 项路线图合入）
> **审计范围**：全量 `src/` 前端视图层（287 个 `.tsx` 组件、全局样式 `src/index.css`、布局骨架 `Layout/Titlebar/Sidebar`、核心对话流 `Chat/MessageList/Message`、**底部消息发送区 `ChatInput/InputCard/ComposerControls/Menus`**、右侧面板 `RightPanel`、设置中心 `Settings`、知识库/Wiki/编排/Office 工作台）。

---

## 一、核心体检结论与量化指标

通过对当前 `src/` 全部 287 个非测试 `.tsx` 组件与样式系统的静态扫描与逐行走查，当前 UI 存在 **9 大类高优体验与视觉一致性问题**：

| 维度 | 量化现状 | 核心痛点 |
|---|---|---|
| **1. 底部发送消息区（Composer）布局与交互** | 单行同时水平并排 `<textarea>` + **5 组右侧控件（共占 `~660px`）**；双重嵌套边框；`@` 菜单无键盘导航且推挤布局 | 中等窗口下 `<textarea>` 被右侧控件水平挤压至仅剩 `100–180px`；外框套内框视觉割裂；输入 `@` 时 `AtEntityMenu` 破坏文档流且按 `Enter` 直接把半截 `@query` 发送出去 |
| **2. 顶栏与导航外壳（App Shell）** | 同屏 2 个 `<BrandLogo>`、左右顶栏高度错位（左 `48px` vs 右 `36px + 48px`）、窄屏抽屉 `setMobileOpen(true)` 零触发入口 | 桌面端左栏与标题栏品牌标识重复、分割线错位；窗口宽度 `< 768px` 时侧边栏被隐藏但无任何汉堡按钮可唤起 |
| **3. 右侧面板（`RightPanel`）头部拥挤** | 默认宽度 `320px`（最小 `280px`）单行塞入 **6 个 Tab + 6 个工具按钮** | 右侧 `S/M/L + 自动展开 + 最大化 + 关闭` 占去 `~188px`，6 个中文 Tab 仅剩 `92px–132px`（每个 Tab 仅 `15–22px`），文字被迫竖排折行或截断 |
| **4. 阻塞式原生弹窗残留** | **12 个组件、34 处** `window.alert` / `window.confirm` / `window.prompt` | `ProvidersManager.tsx` 连续调用 **9 次 `window.prompt()`**（Electron 渲染进程原生不支持 `prompt()`，直接失效）且使用裸 `<table>`；其余 11 个组件阻塞渲染线程 |
| **5. 暗色/自定义主题色值旁路** | **80 个 `.tsx` 文件、558 处**硬编码 Tailwind 调色板（`bg-stone-50`、`text-blue-800` 等） | `WikiQueuePanel.tsx`（41 处）、`LaneBoard.tsx`（24 处）、`RuntimeEnvTab.tsx`（22 处）、`LintItemCard.tsx`（21 处）在暗色模式下出现刺眼白底/浅灰块 |
| **6. 字号标尺与双 CSS 变量割裂** | `font-scale-baseline.json` 仍存 **77 个文件、184 处** `text-[Npx]`；`index.css` 同时存在 `--font-size-ui` 与 `--ui-font-size` | `Message.tsx`（16 处）、`FileChangeCard.tsx`（8 处）、`MemoryBrowser.tsx`（8 处）等未接入语义字号标尺，用户调大字号时局部文字不缩放 |
| **7. 对话主视口纵向挤压** | `Chat.tsx` 在 `MessageList` 上下最多同时堆叠 **7 层横幅/面板** | 当 `PlanCard`、`SubagentLivePanel`、`PendingQueueStrip`、`TerminalPanel` 同时出现时，1366×768 / 1440×900 笔记本上消息滚动区被挤压至 `< 180px` |
| **8. 消息气泡操作栏过载与无障碍缺口** | 单条 Assistant 消息底部平铺 **10+ 个图标按钮**；2 个弹窗缺 `Escape` 关闭 | 操作栏视觉噪点高，`ThumbsUp` / `ThumbsDown` / `Fork` 缺 `aria-label`；`CreateTaskModal` 与 `UpdateDialog` 未接入统一 `Dialog` 容器且按 `Esc` 无响应 |
| **9. 超大 UI 组件单体（>800 行）** | `src/` 下仍有 **7 个视图组件**滞留 `architecture-baseline.json` | `OfficeEditPreviewDialog.tsx`（1,615 行）、`Chat.tsx`（1,300 行）、`Message.tsx`（1,166 行）、`OfficePreviewPanel.tsx`（1,081 行）、`NetworkTab.tsx`（1,001 行）维护与重渲染成本高 |

---

## 二、底部发送消息区（Composer）深度诊断与专项优化方案

底部消息输入区涉及 `ChatInput.tsx`、`InputCard.tsx`、`ComposerPlusMenu.tsx`、`SlashCommandMenu.tsx`、`AtFileMenu.tsx`、`AtEntityMenu.tsx`、`PermissionModeSwitch.tsx`、`ContextMeter.tsx`、`ContextPressureBadge.tsx`、`SessionModelPicker.tsx`、`AttachmentUpload.tsx`、`PendingQueueStrip.tsx` 共 **12 个关联组件**。逐行审查发现以下 **7 个具体体验与交互问题**：

### 2.1 输入框与右侧控制簇单行水平争夺宽度（最严重）
- **代码位置**：`src/widgets/chat/InputCard.tsx:490-619`
- **现状问题**：
  - `InputCard` 使用单行 `<div className="flex items-end gap-2">`，左侧放 `<textarea>`，**同一行右侧**并排放了 5 组控件：
    1. `PermissionModeSwitch`（`[🛡 标准 ▾]` + `[✓ 已自动批准 N 次]`，约 `160px`）
    2. `ContextMeter`（`[━━━━ 45%]`，约 `95px`）
    3. `SessionModelPicker`（`🤖 [跟随全局 (model) ▾]`，最宽 `245px`；触发窗口风险提示时内联展开 `model-switch-warning` 再占 `~380px`）
    4. `+ 新话题` 按钮（约 `84px`）
    5. `发送 / 停止` 按钮（约 `80px`）
  - 右侧控件合计占据 **`~664px`**（含模型切换告警时超 `1000px`）。当左栏（`260px`）与右侧工作台（`320px–480px`）同时打开时，中间对话列总宽仅 `600px–800px`，导致左侧 `<textarea>` 被挤压成仅 **`100px–180px` 宽的窄条**（一行只能打 6~10 个汉字），且外层卡片包内层输入框呈现怪异的“左框右散”形态。
- **优化方案（对标 Claude / Cursor / ChatGPT 双层一体化 Composer 卡片）**：
  - **去掉“框中框”双重边框**，将整个 `InputCard` 作为统一的圆角输入容器（带 `focus-within:border-primary/60` 高亮）；
  - **第一层（输入层）**：`<textarea rows={1}>` 独占 **100% 宽度**，上方紧凑展示已选图片/文件/知识库/Office 引用 Chip；
  - **第二层（底部工具与状态栏）**：
    - 左侧：`[+]` 多功能菜单、`[编排模式紧凑胶囊]`、语音/音频入口；
    - 右侧：`PermissionModeSwitch`、`ContextMeter`、`SessionModelPicker`、`新话题`、`发送/停止` 按钮，窄宽下支持自适应换行或折叠次要文字。

### 2.2 `orchModeBar`（编排模式条）常驻独占一整行顶栏
- **代码位置**：`src/widgets/chat/ChatInput.tsx:760-779` & `InputCard.tsx:401`
- **现状问题**：
  - `编排模式: [自动 ▾]` 默认 95% 时间处于 `auto` 状态，却在 `InputCard` 内部上方独占一整行（带 `border-b border-border`），既增加视觉分割线又浪费纵向空间。
- **优化方案**：
  - 将 `orch-mode-select` 移入 Composer 底部工具栏左侧（紧跟 `[+]` 按钮之后），变为紧凑的胶囊下拉选择器；当切为非 `auto`（如 `强制多智能体` 或模板）时以 `bg-primary/10 text-primary` 高亮显示。

### 2.3 `@` 引用菜单（`AtFileMenu` + `AtEntityMenu`）流式推挤与回车误发送 Bug
- **代码位置**：`src/widgets/chat/ChatInput.tsx:746-758`、`src/features/chat/AtEntityMenu.tsx:28-31`、`src/features/chat/AtFileMenu.tsx:61, 165-180`、`src/widgets/chat/InputCard.tsx:338-387`
- **现状问题**：
  1. **布局跳动**：输入 `@` 时，`AtFileMenu` 是 `position: absolute; bottom: 100%` 浮在输入框上方，而同级渲染的 `AtEntityMenu`（`@memory: / @wiki: / @skill: / @agent:`）**没有绝对定位**，直接插在文档流里把 `<textarea>` 向下推挤一截。
  2. **缺乏键盘上下选择与回车拦截（交互 Bug）**：`InputCard.tsx:339` 的 `handleKeyDown` 只拦截了 `showSlashMenu` 的 `ArrowUp / ArrowDown / Enter / Escape`，**完全没有处理 `@` 菜单打开时的键盘事件**。当用户输入 `@readme` 后习惯性按 `ArrowDown` 或 `Enter` 想选中第一个文件时，**不仅选不中文件，反而会直接触发 `onSubmit()` 把半截未写完的消息发送出去**！
  3. **`SlashCommandMenu` 缺少滚动上限**：`SlashCommandMenu.tsx:15` 未设置 `max-h-64 overflow-y-auto`，当技能与自定义 Prompt 模板较多时菜单会向上溢出屏幕。
- **优化方案**：
  - 将 `AtEntityMenu` 与 `AtFileMenu` 收纳进同一个 `bottom-full mb-2` 绝对定位浮层容器内（顶部为实体类型快捷胶囊，下方为文件搜索结果列表），彻底消除输入 `@` 时的输入框跳动；
  - 为 `@` 菜单补齐 `ArrowUp / ArrowDown / Enter / Escape` 键盘导航，并在 `@` 菜单激活时拦截 `Enter` 键防止误发送消息；
  - 为 `SlashCommandMenu` 增加 `max-h-64 overflow-y-auto` 及当前选中项 `scrollIntoView({ block: 'nearest' })`，并统一使用 Tailwind 类替代 `AtFileMenu` 中的内联 `style={{ ... }}`。

### 2.4 音频上传按钮图标误导与上传后未接线（`AttachmentUpload.tsx` + `ChatInput.tsx:629-635`）
- **代码位置**：`src/features/send-message/AttachmentUpload.tsx:136, 158`、`src/widgets/chat/ChatInput.tsx:629-635`
- **现状问题**：
  1. `AttachmentUpload` 只接受音频文件（`.wav/.mp3/.ogg/.webm/.flac`），但按钮直接渲染了Emoji 回形针 `📎`（与通用文件附件语义冲突），且报错信息使用硬编码 `#d32f2f` 直接撑开输入框行；
  2. `ChatInput.tsx:629-635` 中 `handleAudioAttachment` 内部仅有 `// TODO: integrate with message sending` 和 `console.warn`，用户上传音频后既无附件 Chip 展示，发送消息时也不会携带音频引用。
- **优化方案**：
  - 将图标替换为明确的 `Mic` / `FileAudio` 图标，错误提示统一走 `toast.error`；
  - 在 `ChatInput` 中将上传成功的音频加入附件 Chip 列表（支持预览文件名/大小与移除），并在发送时随消息一并透传或追加引用说明。

### 2.5 上下文水位重复渲染（`ContextPressureBadge` vs `ContextMeter`）
- **代码位置**：`src/pages/Chat.tsx:1209, 1237`
- **现状问题**：
  - 输入框正上方渲染了 `<ContextPressureBadge />`（`≥ 60%` 时显示琥珀/红色横条），而输入框右下角又常驻渲染了 `<ContextMeter />`（进度条 + 百分比）。当上下文达到 60% 以上时，上下相邻两行重复显示同一个百分比。
- **优化方案**：
  - 将 `ContextPressureBadge` 的水位告警能力融合进 `ContextMeter`（当 `pressure ≥ 0.6` 时在 `ContextMeter` 胶囊上高亮琥珀/红底并支持一键点击 `/compact` 压缩上下文），省去输入框上方冗余的独立横条。

### 2.6 `SessionModelPicker` 切换风险确认内联撑爆工具栏
- **代码位置**：`src/widgets/chat/SessionModelPicker.tsx:153-184`
- **现状问题**：
  - 当切换到小窗口模型触发 `pendingSwitch` 告警时，提示文案与 `[仍然切换] [取消]` 按钮直接以 `<span>` 内联渲染在 `composerControls` 行内，瞬间把工具栏横向撑宽 `350px+`。
- **优化方案**：
  - 将 `model-switch-warning` 改为锚定在模型选择器正上方的浮层卡片（`absolute bottom-full right-0 mb-2 w-72`），不挤压底部工具栏布局。

### 2.7 横幅边距不对齐与底部提示条优化
- **代码位置**：`src/widgets/chat/ChatInput.tsx:694`、`src/widgets/chat/PendingQueueStrip.tsx:39`、`src/widgets/chat/InputCard.tsx:502, 643`
- **现状问题**：
  - `edit-resend-banner` 使用了 `mx-4`，`PendingQueueStrip` 使用了 `px-3`，而 `InputCard` 是无外边距的全宽块，三者左右边缘参差不齐；
  - `<textarea>` 未设置 `rows={1}`，首次挂载在 `useEffect` 生效前会按浏览器默认 2 行高度渲染再跳回 1 行。
- **优化方案**：
  - 统一 `edit-resend-banner`、`PendingQueueStrip` 与 `InputCard` 的外边距与圆角衔接；为 `<textarea>` 显式加上 `rows={1}`。

---

## 三、其余模块问题定位与代码级证据

### 3.1 外壳与导航层（`Layout.tsx` / `Titlebar.tsx` / `Sidebar.tsx`）

1. **窄屏/小窗口（`< 768px`）侧边栏完全无法打开（功能性 Bug）**：
   - 在 `src/widgets/layout/Layout.tsx:23-37` 中，当 `window.innerWidth < 768` 时，`isMobile` 为 `true`，桌面侧栏被替换为抽屉层（`mobileOpen ? 'translate-x-0' : '-translate-x-full'`）。
   - 然而全仓没有任何地方调用 `setMobileOpen(true)`（仅在 `onResize` 和遮罩点击时调用 `setMobileOpen(false)`），导致用户将窗口缩窄至 `< 768px` 或在分屏模式下使用时，**侧边栏消失且没有任何按钮可以唤出**。
2. **双 `<BrandLogo>` 与顶栏分割线错位**：
   - `Sidebar.tsx:393` 在左栏 56px rail 顶部渲染 `h-12`（48px）的 `<BrandLogo size="sm" />`，紧接着在展开内容列顶部（`Sidebar.tsx:507`）渲染 `h-12` 的品牌名；
   - 而右侧 `Titlebar.tsx:42-45` 在 Windows/Linux 下又渲染了一行 `h-9`（36px）的 `<BrandLogo size="xs" />`，其下方 `Chat.tsx:909` 再渲染一行 `h-12`（48px）的页面头部。左右两侧的 `border-b` 水平线高度差达 `12px`，且左上角相邻出现两个同品牌 Logo。
3. **同屏重复的「新建对话」入口**：
   - `Sidebar.tsx:513` 顶部已有主操作按钮 `新建对话 (Ctrl+N)`，`Chat.tsx:944` 右上角又放置了一个 `+ 新对话` 按钮，挤占了对话头部的状态展示空间。

### 3.2 右侧工作台面板（`RightPanel.tsx`）

- **Header 单行 6 Tab + 6 按钮溢出（`RightPanel.tsx:181-206`）**：
  - `RIGHT_PANEL_TABS` 包含 6 个标签：`进度`、`目录`、`轨迹`、`变更 (N)`、`预览`、`产物 (N)`。
  - 同一行右侧常驻 `AutoOpenToggle`（当在产物 Tab 时）+ `S` / `M` / `L` 三档宽度按钮 + `最大化` + `关闭` 共 5–6 个按钮（宽约 `160px–188px`）。
  - 在默认 `S` 档（`320px`）或最小拖拽宽度（`280px`）下，6 个 Tab 按钮（`flex-1 min-w-0 py-2 text-sm`）平均每个仅分到 `15px–22px` 宽度，导致中文字符竖排折行甚至带计数时（如 `产物 (2)`）严重截断。

### 3.3 原生阻塞弹窗清理（12 个文件、34 处调用）

Electron 渲染进程中 `window.prompt()` 原生不支持（返回 `null` 或抛错），而 `window.alert()` / `window.confirm()` 会冻结渲染进程事件循环并破坏无边框窗口焦点：

| 文件路径 | 残留调用 | 替换方案 |
|---|---|---|
| `src/pages/settings/ProvidersManager.tsx` | **9 处 `window.prompt` + 5 处 `window.alert`**（且使用未样式化的裸 `<table>`） | 重构为受控表单 Modal（使用 `<Dialog>` + `<input type="password">` 输入 Token）+ `toast.success/error` + 标准 Tailwind 卡片表格 |
| `src/pages/settings/MemoryTab.tsx` | 4 处 `window.alert` | 替换为 `toast.error` / `toast.success` |
| `src/widgets/session/SessionItem.tsx` | 3 处 `alert` | 替换为 `toast.error` |
| `src/widgets/wiki/SourcesView.tsx` | 2 处 `alert` + 1 处 `confirm` | 替换为 `toast.error` + `confirmDialog` |
| `src/pages/settings/PromptTemplatesTab.tsx` | 2 处 `window.alert` | 替换为 `toast.error` |
| `src/pages/settings/NetworkTab.tsx` | 1 处 `window.alert` | 替换为 `toast.error` |
| `src/features/project-type/ConstraintManager.tsx` | 1 处 `confirm` | 替换为 `confirmDialog` |
| `src/features/project-type/MilestoneManager.tsx` | 1 处 `confirm` | 替换为 `confirmDialog` |
| `src/features/task-brief/SavedTaskRecipes.tsx` | 1 处 `window.confirm` | 替换为 `confirmDialog` |
| `src/pages/settings/ThemeSelector.tsx` | 1 处 `confirm` | 替换为 `confirmDialog` |
| `src/widgets/memory/MemoryBrowser.tsx` | 1 处 `window.confirm` | 替换为 `confirmDialog` |
| `src/widgets/wiki/WikiQueuePanel.tsx` | 1 处 `confirm` | 替换为 `confirmDialog` |

### 3.4 暗色模式与语义色值对齐（80 个文件、558 处硬编码调色板）

- **重灾区 Top 10**：
  1. `src/widgets/wiki/WikiQueuePanel.tsx`（**41 处**：`bg-stone-50`、`border-stone-200`、`text-stone-800` 等，暗色模式下整块发白）
  2. `src/widgets/orchestration/LaneBoard.tsx`（**24 处**：`bg-blue-100 text-blue-800`、`bg-green-100 text-green-800` 等）
  3. `src/pages/settings/RuntimeEnvTab.tsx`（**22 处**）
  4. `src/widgets/wiki/LintItemCard.tsx`（**21 处**）
  5. `src/pages/settings/EndpointsTab.tsx`（**19 处**）
  6. `src/widgets/orchestration/LaneDetailDrawer.tsx`（**19 处**）
  7. `src/pages/settings/McpTab.tsx`（**18 处**）
  8. `src/features/office/OfficeDeliveryDrawer.tsx`（**16 处**）
  9. `src/features/project-type/ProjectTypeBadge.tsx` & `ProjectTypeSelector.tsx`（**各 16 处**）
  10. `src/widgets/chat/changes/ChangesSection.tsx` & `FileChangeCard.tsx`（**各 14 处**）

### 3.5 消息气泡底部操作栏减负与弹窗无障碍收口

1. **消息底部操作栏分级披露（Progressive Action Bar）**：
   - **一级常驻操作**保留最常用的 4 项：`复制`、`引用`、`重新生成`、`有帮助/没帮助`（及右侧 `版本切换` / `生成统计`）；
   - **二级低频/破坏性操作**（`朗读`、`从此处分叉`、`回滚到此轮`、`保存到记忆`、`删除消息`）收纳进紧凑的 `更多 (⋯)` 下拉菜单，并补齐 `ThumbsUp`、`ThumbsDown`、`Fork` 等图标按钮缺失的 `aria-label`。
2. **统一 `Dialog` 容器与 `Escape` 键支持**：
   - `src/features/scheduled/CreateTaskModal.tsx` 与 `src/components/UpdateDialog.tsx` 补齐 `Escape` 键关闭监听与焦点管理；`src/widgets/system/ShortcutHelpOverlay.tsx` 补齐 `aria-modal="true"`。

---

## 四、分批落地执行路线图（UI 专项）

为确保每次改动小步快跑、双轨（`main` + `release/win7`）零回归，建议按以下 **3 个批次（P0 → P1 → P2）** 推进：

### P0 批次：底部发送区重构、阻断性交互修复与原生弹窗清零（最高优先级）

| 编号 | 任务名称 | 涉及文件 | 验收标准 |
|---|---|---|---|
| **UI-P0-1** | **重构底部消息发送区（Composer）为双层一体化卡片 & 修复 `@` / `/` 菜单交互** | `InputCard.tsx`, `ChatInput.tsx`, `AtEntityMenu.tsx`, `AtFileMenu.tsx`, `SlashCommandMenu.tsx`, `SessionModelPicker.tsx`, `AttachmentUpload.tsx` | ① `<textarea rows={1}>` 独占 100% 宽度，消除双重边框与右侧 5 组控件水平挤压；② `orchModeBar` 收纳进底部工具栏；③ `@` 菜单整合为统一浮层并支持 `↑/↓/Enter/Esc` 导航且不误发消息；④ `SlashCommandMenu` 支持滚动上限；⑤ 模型切换风险告警改为浮层弹出；⑥ 音频上传改为麦克风/音频图标并展示已上传音频 Chip |
| **UI-P0-2** | **修复窄屏（`<768px`）侧边栏无法唤出 & 消除双 BrandLogo** | `src/widgets/layout/Layout.tsx`, `src/widgets/layout/Titlebar.tsx` | 窄屏下 `Titlebar` 左侧显示侧栏唤起按钮并可正常开关抽屉；桌面端消除重复的左二 Logo |
| **UI-P0-3** | **修复 `RightPanel` 头部 6-Tab 在默认宽度下的文字挤压折行** | `src/widgets/chat/RightPanel.tsx` | `280px–320px` 宽度下 6 个 Tab 单行清晰可读（`whitespace-nowrap text-xs` + 工具栏紧凑布局），零竖排折行 |
| **UI-P0-4** | **重构 `ProvidersManager` 为受控表单并清零全仓 34 处原生 `alert/confirm/prompt`** | `ProvidersManager.tsx` 及另外 11 个含原生弹窗的 `.tsx` 文件 | 全仓业务组件 `window.alert/confirm/prompt` 清零（`0` 处），新增单测防回潮 |
| **UI-P0-5** | **补齐弹窗 `Escape` 关闭、`aria-modal` 与消息操作栏 `aria-label`** | `CreateTaskModal.tsx`, `UpdateDialog.tsx`, `ShortcutHelpOverlay.tsx`, `Message.tsx` | 所有 `role="dialog"` 均支持 `Escape` 关闭且具备 `aria-modal="true"`；`Message.tsx` 图标按钮 100% 具备 `aria-label` |

### P1 批次：暗色模式语义色值对齐与字号标尺二期（视觉一致性提升）

| 编号 | 任务名称 | 涉及文件 | 验收标准 |
|---|---|---|---|
| **UI-P1-1** | **清理 Top 10 重灾组件的硬编码亮色 Tailwind 调色板（200+ 处）** | `WikiQueuePanel.tsx`, `LaneBoard.tsx`, `LaneDetailDrawer.tsx`, `LintItemCard.tsx`, `ReviewItemCard.tsx`, `RuntimeEnvTab.tsx`, `EndpointsTab.tsx`, `McpTab.tsx`, `ChangesSection.tsx`, `FileChangeCard.tsx` | 全部迁移至语义令牌（`bg-surface`、`bg-bg-subtle`、`text-text`、`bg-primary/10`、`bg-success/10` 等），暗色模式下零刺眼白底 |
| **UI-P1-2** | **统一 `--font-size-ui` / `--ui-font-size` 并迁移 Top 8 组件的 63 处硬编码字号** | `src/index.css`, `Message.tsx`, `FileChangeCard.tsx`, `MemoryBrowser.tsx`, `PromptTemplatesTab.tsx`, `EndpointsTab.tsx`, `RuntimeEnvTab.tsx`, `BlockedCard.tsx`, `PermissionModeSwitch.tsx` | `node scripts/check-font-scale.mjs --tighten` 永久下调基线 **60+ 处**，上述 8 个高频组件从 `font-scale-baseline.json` 中彻底移除 |

### P2 批次：核心大组件减负与对话流视觉降噪（架构与性能）

| 编号 | 任务名称 | 涉及文件 | 验收标准 |
|---|---|---|---|
| **UI-P2-1** | **`Message.tsx`（1,166 行）子组件拆分与底部操作栏渐进披露** | `src/widgets/chat/Message.tsx` + 拆出 `MessageActionBar.tsx` / `MessageMarkdownBody.tsx` | `Message.tsx` 降至 `< 800` 行并彻底退出 `architecture-baseline.json`；底部操作栏清爽分级 |
| **UI-P2-2** | **`OfficeEditPreviewDialog.tsx`（1,615 行）按文档类型拆分编辑器子表单** | `src/features/office/OfficeEditPreviewDialog.tsx` + `WordEditFields.tsx` / `ExcelEditFields.tsx` / `PptEditFields.tsx` | `OfficeEditPreviewDialog.tsx` 降至 `< 800` 行并彻底退出 `architecture-baseline.json` |
| **UI-P2-3** | **`Chat.tsx`（1,300 行）抽离头部与底部状态条组合组件并合并上下文水位** | `src/pages/Chat.tsx` + `ChatHeaderBar.tsx` / `ChatBottomStatusStack.tsx` | `Chat.tsx` 降至 `< 800` 行并彻底退出 `architecture-baseline.json`；合并重复的上下文水位提示，释放对话纵向可视空间 |
