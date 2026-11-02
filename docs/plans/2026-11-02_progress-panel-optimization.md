# 进度面板优化方案（2026-11-02）

## 背景与目标

当前右侧进度面板（`ProgressSection`）将任务清单、编排计划、子agent 执行树、历史 run 平铺在同一滚动区，存在以下问题：

1. **信息过载**：todos + 编排计划 + TaskTree + RunHistory 全部堆叠，用户难以快速感知"现在在做什么"
2. **视觉噪声**：TaskTreeSection 每行堆叠 6-8 个徽章（retry × N / blocked-by / adjusted / redeploy / tokens / duration / skip / retry 按钮），信息密度过高
3. **子agent 实时情况不可见**：点击任务打开的 `SubagentDetailDrawer` 是 `absolute w-96`（384px）嵌在宽 320-560 的面板内，内容被裁切；且只展示事件时间线，没有实时 LLM 输出流
4. **编排计划与 TaskTree 重复**：`TodoListSection` 内的编排计划镜像与 `TaskTreeSection` 数据来源相同，展示重复

参考主流 AI 应用（Cursor Tasks、Devin Timeline、Windsurf Live Log、ChatGPT Deep Research），目标：
- **一眼可知**：当前状态 + 进度 + 正在做什么
- **按需深入**：点击任务查看完整详情（全宽面板，不是嵌在面板内的小 drawer）
- **视觉简洁**：列表只保留关键信息，次要信息移入详情

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `src/widgets/chat/progress/ProgressSection.tsx` | 重构：sub-tab 改为"概览/任务/轨迹" |
| `src/widgets/chat/progress/StatusBar.tsx` | 新增：进度条视觉 + 状态 + 耗时 + 操作按钮 |
| `src/widgets/chat/progress/CurrentTaskFocus.tsx` | 新增：当前 running 任务焦点卡 |
| `src/widgets/chat/progress/TaskTreeSection.tsx` | 简化：徽章瘦身，次要信息移入 TaskDetailView |
| `src/widgets/chat/progress/TodoListSection.tsx` | 简化：移除编排计划镜像（合并到 TaskTree） |
| `src/widgets/chat/progress/TaskDetailView.tsx` | 新增：替代 SubagentDetailDrawer，全宽详情视图 |
| `src/widgets/chat/progress/SubagentDetailDrawer.tsx` | 删除（功能由 TaskDetailView 替代） |

## 技术方案

### 三层信息架构

```
Progress Tab
├─ sub-tab: "概览" | "任务" | "轨迹"
│
├─ [概览] sub-tab（默认）
│   ├─ StatusBar（固定顶栏）：状态 + 进度条 + 耗时 + 操作
│   └─ CurrentTaskFocus：当前 running 任务焦点卡（点击 → 切到"任务"并打开详情）
│       └─ 无 running 任务时显示摘要（"全部完成" / "等待输入"）
│
├─ [任务] sub-tab
│   ├─ 简洁列表：状态图标 + agent + 目标 + (running) liveStep + (终态) 耗时
│   │   └─ 次要信息（tokens/retry/blocked-by/adjusted/redeploy）移入详情
│   └─ 点击任务 → 整面板切换为 TaskDetailView
│       ├─ 头部：← 返回 + agent + 状态 + 耗时 + tokens
│       ├─ 当前步骤（大字体）+ output_preview / error
│       ├─ 实时事件时间线（EventTimeline，全宽）
│       └─ ContextInput（steering，仅 running 任务）
│
└─ [轨迹] sub-tab（保留，不变）
```

### 具体变更

**P1 — StatusBar 抽离**
- 从 `ProgressSection` 顶部的状态行抽成独立组件
- 进度条视觉（`div.w-full.bg-bg-hover > div.bg-primary`）替代纯文本 "3/8 完成"
- 取消/自动批准按钮从 TaskTreeSection 移到 StatusBar
- 总耗时 + tokens 求和移到这里

**P2 — TaskTreeSection 徽章瘦身**
列表项从：
```
[状态][依赖][▶/▼][耗时][agent][目标][跳过][重试][重试×N][tokens·duration][blocked-by][重派][已调整]
[等待审批...]
[liveStep...]
[实时动态(N条)]
[结果预览]
```
简化为：
```
[状态][agent][目标]                          [(running)耗时][(终态)tokens·duration]
       [(running)liveStep...]
```
- 保留：状态图标、agent 标签、目标、running 耗时、终态 tokens+duration、liveStep
- 移入详情：依赖行、折叠按钮、跳过/重试按钮（移到详情头部）、retry count、blocked-by、重派、已调整、实时动态（details）、结果预览（details）

**P3 — TaskDetailView 替代 SubagentDetailDrawer**
- 整面板替换（ProgressSection 渲染 TaskDetailView 替代列表）
- 全宽展示 EventTimeline + output_preview
- 头部：← 返回 + agent + 状态徽章 + 耗时 + tokens + 跳过/重试按钮
- 保留 ContextInput（仅非终态任务）

**P4 — sub-tab 三切分**
- "实时进度" → 拆成"概览" + "任务"
- "概览"：StatusBar + CurrentTaskFocus
- "任务"：简化后的 TaskTreeSection（含 todos + 编排计划，去重）
- "轨迹"：保留

**P5 — CurrentTaskFocus 焦点卡**
- 从 `board.statuses` 找到 status === 'running' 的任务（取 runningSince 最早的）
- 显示：agent + 目标 + liveStep（大字体 animate-pulse）+ 已运行时长
- 点击 → 切到"任务" sub-tab + 打开该任务的 TaskDetailView
- 无 running 任务时：显示"全部完成 ✓"或"等待输入..."

**P6 — 编排计划去重**
- `TodoListSection` 移除编排计划镜像（`taskBoard.plan.map(...)` 部分）
- 编排计划由 `TaskTreeSection` 统一展示（已有）
- `TodoListSection` 只展示 agent 自建 todos

## 实施步骤

- [x] P1：StatusBar 抽离
- [x] P2：TaskTreeSection 徽章瘦身
- [x] P3：TaskDetailView 新增（替代 SubagentDetailDrawer）
- [x] P4：ProgressSection sub-tab 三切分
- [x] P5：CurrentTaskFocus 焦点卡
- [x] P6：TodoListSection 去重
- [x] 测试：更新现有测试（SubagentDetailDrawer → TaskDetailView）
- [x] tsc 类型检查 + 进度面板相关 12 文件 80 用例全绿
- [x] CI 绿后提交 → PR（main PR #2799 已合并；win7 PR #2804 已开，等 CI）

## 风险评估

| 风险 | 缓解 |
|------|------|
| 现有测试依赖 SubagentDetailDrawer testid | 新 TaskDetailView 保留等效 testid 或更新测试 |
| TaskTreeSection 简化后丢失信息 | 所有次要信息可在 TaskDetailView 查看，不丢失 |
| 用户习惯改变 | sub-tab 切分清晰，"概览"默认视图更聚焦 |
