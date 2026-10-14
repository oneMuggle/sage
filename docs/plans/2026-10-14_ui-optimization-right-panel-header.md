# UI 优化方案：右侧面板重构 + 顶栏控件收敛 + 左右面板联动

> 创建日期：2026-10-14
> 状态：已实施（15/15 步骤完成，全量前端测试 476 文件 / 3445 用例绿，tsc + eslint 绿）
> 分支：`ui-optimization-right-panel-header`

## 背景与目标

当前三栏布局（左 Sidebar / 中 Chat / 右 RightPanel）对标 Claude artifacts 面板设计，架构合理，
但存在三个主要问题：

1. **右栏 Tab 过多**（6 个），分类混乱，S 档下每个 Tab 仅 ~50px，文字截断严重
2. **顶栏控件过密**（8 个），右栏打开时大量文字标签隐藏，只剩图标，认知负荷高
3. **左右面板无联动**，右栏最大化时左栏不配合退让，中间区域可能窄到无法阅读

**目标**：在不改变整体三栏架构的前提下，降低信息架构复杂度、减少视觉噪音、提升宽屏利用率。

**不在范围内**：
- ActiveAgentIndicator 位置调整（用户评估为可接受，保持现状）
- 左 Sidebar 内部结构变更
- 移动端布局调整

---

## 一、右侧面板 Tab 合并（6→4）

### 现状

| Tab | 内容 | 使用频率 |
|-----|------|---------|
| progress | 工具执行进度 / 任务板 / Todo | 高（流式期间） |
| artifacts | 生成文件列表 + 详情查看器 | 中 |
| changes | 工作区文件变更 + Git diff | 中 |
| outline | 轮次导航 + 标题大纲 | 高（长对话） |
| trajectory | 会话级时间线 + 工具 payload | 低（调试） |
| preview | 文档预览（从变更跳入） | 低（常态为空） |

### 问题

- 「轨迹」与「进度」都是运行时信息，分离不合理
- 「预览」常态为空，独立占一个 Tab 是浪费
- 「产物」和「预览」都属于产出物查看，合并更自然

### 目标 Tab 结构

| 新 Tab | 合并来源 | 说明 |
|--------|---------|------|
| **进度** | progress + trajectory | 进度为主视图，轨迹降为进度 Tab 内的 sub-tab |
| **产物** | artifacts | 产物列表 + ArtifactViewer 详情（不变） |
| **变更** | changes + preview | 文件变更 + diff；从变更点「预览」在 Tab 内 inline 展开预览区，不跳 Tab |
| **目录** | outline（不变） | 保留，轮次导航 + 标题大纲 |

### 关键设计决策

**轨迹在进度 Tab 内的呈现方式**：

- 方案 A：进度 Tab 顶部加两个 sub-tab（`实时进度` / `轨迹`）
- 方案 B：进度 Tab 底部折叠区「查看完整轨迹」，点击展开 TrajectoryPane

✅ 确定 **方案 A**：进度 Tab 顶部加两个 sub-tab（`实时进度` / `完整轨迹`），默认激活「实时进度」。
轨迹从独立 Tab 降为进度 Tab 的子视图，用户可在两个 sub-tab 间切换，位置固定，不会找不到。

**预览的呈现方式（实施后修订）**：

预览独立 Tab 移除后，`selectPreview()` 改为切到「变更」Tab 并携带 `previewOnSelect` +
`autoPreviewMode`，由 `ChangesSection` 在同一 Tab 内 inline 展开预览区。原先「若预览目标不是产物
则留在变更 Tab」的分支被这条统一路径覆盖，用户不再需要跨 Tab 跳转。

### 涉及文件

- `src/widgets/chat/RightPanel.tsx` — Tab 定义、PanelHeader 渲染逻辑
- `src/features/right-panel/rightPanelStore.ts` — `RightPanelTab` 类型定义、默认 Tab
- `src/widgets/chat/progress/ProgressSection.tsx` — 需嵌入 sub-tab 切换（实时进度 / 完整轨迹）
- `src/widgets/chat/TrajectoryPane.tsx` — 作为进度 Tab 的第二个 sub-tab 视图嵌入
- `src/widgets/chat/artifacts/ArtifactsSection.tsx` — 需支持 inline 预览模式
- `src/widgets/chat/changes/ChangesSection.tsx` — 预览入口调整

---

## 二、顶栏控件收敛

### 现状

`ChatHeaderBar` 右侧有 8 个控件：

```
SessionModelPicker | PermissionModeSwitch | ContextMeter | 编排模式 select | 新话题 | 临时聊天 | 新对话 | 右面板开关
```

### 问题

- 右栏打开时，`rightPanelOpen=true` 触发大量 `hidden xl:inline` / `hidden 2xl:inline`，
  只剩图标，用户难以理解功能
- 「新话题」和「新对话」都带 `+` 前缀，语义容易混淆
- PermissionModeSwitch 和 ContextMeter 是会话级设置，常态显示属于信息过载

### 目标控件布局

**左侧**（不变）：
- 「对话」标题 + ProjectBadge + WorkspaceBranchPicker + SessionUsageBadge

**右侧**（收敛后）：

| 控件 | 处理方式 |
|------|---------|
| SessionModelPicker | 保留（高频操作） |
| 编排模式 select | 保留（编排场景核心） |
| SessionSessionMenu（新） | 合并「新对话」+「新话题」+「临时聊天」为一个下拉菜单 |
| SessionSettingsMenu（新） | 收纳 PermissionModeSwitch + ContextMeter |
| RightPanelToggle | 保留 |

### SessionSessionMenu 设计

触发：一个 `+` 按钮（`MessageSquarePlus` 图标），点击弹出下拉菜单：

```
┌─────────────────────────────┐
│ + 新对话            Ctrl+N  │
│ ↻ 新话题（重置上下文）       │
│ ─────────────────────────── │
│ 🕶 临时聊天（本次不记忆）     │
└─────────────────────────────┘
```

- 「新对话」：创建全新会话（原有 `onNewSession` 逻辑）
- 「新话题」：当前会话内插入分隔符重置上下文（原有 `onNewTopic` 逻辑）
- 「临时聊天」：toggle 当前会话的 memory-disabled 状态（原有 `setTempChatSessions` 逻辑）
- 分割线区分会话创建类操作和状态切换类操作

### SessionSettingsMenu 设计

触发：一个齿轮图标按钮（`Settings` 图标，lucide-react），点击弹出浮层：

```
┌──────────────────────────────────┐
│ 权限模式                          │
│ [auto ▼]  （现有 PermissionModeSwitch）│
│ ──────────────────────────────── │
│ 上下文用量                        │
│ ████████░░ 68%                   │
│ （现有 ContextMeter 内容）         │
└──────────────────────────────────┘
```

### 涉及文件

- `src/pages/chat/ChatHeaderBar.tsx` — 重构右侧控件布局
- 新增 `src/pages/chat/SessionSessionMenu.tsx` — 下拉菜单组件
- 新增 `src/pages/chat/SessionSettingsMenu.tsx` — 浮层组件
- `src/widgets/chat/PermissionModeSwitch.tsx` — 适配为浮层内嵌形式
- `src/widgets/chat/ContextMeter.tsx` — 适配为浮层内嵌形式

---

## 三、左右面板联动

### 现状

- 左栏宽度：`collapsed` state（boolean）+ `width`（260~480px），完全独立
- 右栏宽度：`useResizablePanel`（280~900px），独立 state
- 右栏 `maximized` 时：`width: 100%`，覆盖内容行，但左栏不收缩
- 结果：右栏最大化 + 左栏展开 = 中间区域被压到极窄

### 联动策略

引入一个 `useContentLayout` hook（或在现有 store 中增加字段），定义三种布局模式：

| 模式 | 触发条件 | 左栏 | 右栏 | 中间区 |
|------|---------|------|------|--------|
| `normal` | 默认 | 展开（260~480px） | 关闭或 S 档 | 最大化 |
| `focused` | 右栏打开 + 设置开启 | 折叠到 rail（56px） | 可调（280~720px） | 剩余 |
| `maximized` | 右栏最大化 | 折叠到 rail（56px） | 100%（覆盖内容行） | 被覆盖 |

**核心规则**：

- 联动行为受设置开关控制：「右栏打开时自动折叠左栏」（默认**关闭**）
- 设置开启后：右栏从关闭 → 打开时，若左栏是展开态，自动将左栏折叠到 rail
- 右栏关闭时，**不**自动恢复左栏（避免用户手动展开后又被打断）
- 右栏最大化时，左栏始终折叠到 rail（56px），不受设置开关影响（最大化的语义优先）
- 设置项位置：RightPanel「选项」浮层 → 「右栏打开时折叠左栏」toggle（实施后修订，原写设置页）

### 实现方案

设置项存储在 `rightPanelStore` 的 localStorage helper（**实施后修订**：原方案写 `useSettings`
store，但 `AppSettings` 走后端 REST API 持久化，新增字段需同步改 Python `SettingsPayload` +
DB 列 + 迁移；右栏面板偏好本就全部走 localStorage —— `right-panel-open` / `right-panel-tab` /
`right-panel-auto-open` / `right-panel-width` —— 沿用同一惯例成本更低）。
`Layout.tsx` 监听 `rightPanelStore.open` + `isAutoCollapseSidebarEnabled()`：

```typescript
// Layout.tsx
const rightPanelOpen = useRightPanelStore((s) => s.open);

useEffect(() => {
  if (rightPanelOpen && isAutoCollapseSidebarEnabled()) {
    setCollapsed(true);
  }
  // 右栏关闭时不自动恢复（用户可手动 Ctrl+B 展开）
}, [rightPanelOpen]);
```

设置项 UI 放在 RightPanel 的「选项」浮层（与档位 / 产物自动唤起开关同处），非设置页。

### 涉及文件

- `src/widgets/layout/Layout.tsx` — 新增 rightPanelOpen + autoCollapse 联动逻辑

> **实施后修订**：原计划的 `useSettings.ts` 新字段 + 设置页 toggle 两项**未实施**，改为
> `rightPanelStore` 的 `isAutoCollapseSidebarEnabled` / `setAutoCollapseSidebarEnabled`
> localStorage helper + RightPanel `PanelOptionsMenu` 内 toggle（见上）。

---

## 实施顺序

### Phase 1：右栏 Tab 合并（6→4）

- [x] 步骤 1：修改 `rightPanelStore.ts`，`RightPanelTab` 从 6 个缩减为 4 个
- [x] 步骤 2：重构 `RightPanel.tsx` 的 Tab 渲染和内容分发逻辑
- [x] 步骤 3：在 `ProgressSection` 顶部增加 sub-tab 切换（实时进度 / 完整轨迹），嵌入 TrajectoryPane
- [x] 步骤 4：调整 `ArtifactsSection` 支持 inline 预览（或保持 ArtifactViewer 不变，但 Tab 入口合并）
- [x] 步骤 5：调整 `ChangesSection` 的预览入口逻辑
- [x] 步骤 6：更新相关测试断言（`RightPanel.test.tsx` 5 Tab→4 Tab + 轨迹 sub-tab 用例）

### Phase 2：顶栏控件收敛

- [x] 步骤 7：实现 `SessionSessionMenu` 下拉菜单组件
- [x] 步骤 8：实现 `SessionSettingsMenu` 浮层组件
- [x] 步骤 9：重构 `ChatHeaderBar.tsx`，替换原有控件排列
- [x] 步骤 10：更新 ChatHeaderBar 相关测试（`Chat.welcome-routing.test.tsx` 两步点击、`Message.r2ReadingPolish.test.tsx` testid；新增 `chatHeaderMenus.test.tsx` 9 用例）

### Phase 3：左右面板联动 + 设置项

- [x] 步骤 11：在 `rightPanelStore` 增加 `isAutoCollapseSidebarEnabled` / `setAutoCollapseSidebarEnabled`（localStorage，默认 false）
- [x] 步骤 12：在 RightPanel `PanelOptionsMenu` 增加「右栏打开时折叠左栏」toggle
- [x] 步骤 13：在 `Layout.tsx` 增加 rightPanelOpen + autoCollapse → collapsed 联动
- [x] 步骤 14：右栏最大化时左栏始终折叠（不受设置开关影响）
- [x] 步骤 15：添加联动逻辑测试（新增 `Layout.panelCoordination.test.tsx` 4 用例）

---

## 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| Tab 合并后用户找不到「轨迹」功能 | 低 | 进度 Tab 内有明确 sub-tab「完整轨迹」，位置固定 |
| 顶栏下拉菜单比原按钮多一次点击 | 低 | 高频操作（新对话）在菜单首位，键盘 ↑/↓ 可达 |
| 测试断言大面积变更 | 中 | Phase 1 先做，逐步验证；不在一个 PR 里全改 |

---

## 已确认决策

| # | 决策 | 结论 |
|---|------|------|
| 1 | 轨迹在进度 Tab 的呈现方式 | sub-tab（方案 A）：进度 Tab 顶部「实时进度 / 完整轨迹」 |
| 2 | 右栏打开自动折叠左栏 | 可选设置，默认**关闭**（设置面板「外观 / 布局」分组） |
| 3 | SessionSessionMenu 触发按钮 | `+` 图标（`MessageSquarePlus`） |
| 4 | SessionSettingsMenu 触发图标 | 齿轮图标（`Settings`，lucide-react） |
