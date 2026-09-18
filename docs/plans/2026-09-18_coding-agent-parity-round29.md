# 编码代理对标差距分析·第二十九轮：运行中子任务实时耗时（BU15）

- **状态**：批次 A 交付中（分支 `feat-parity-r29-batch-a`，基线 origin/main 2be6a18f = #1164）
- **上游文档**：round24（BU13 终态 duration_ms——只在终态可见，运行中无感知）
- **对标对象**：Claude Code（运行中 Task 实时计时）、Devin（步骤实时耗时）
- **编号约定**：延续 BU 系

## 0. 结论速览

BU13 让终态任务带 `duration_ms`，但 running 任务行只有 "◐" 图标——
**卡住的子任务用户无法察觉**（10 秒与 10 分钟的 running 长得一模一样）。
本轮在任务树 running 行内加实时计时徽章（前端 ingestion 打时间戳 +
1s tick），长任务一眼可辨。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU15 | running 行无实时耗时 | TaskTreeSection 运行行仅图标+goal | Claude Code 实时计时 | **P3** |

## 2. 设计（批次 A：BU15）

- **ingestion**：`orchestrationEvents.ts` task_status 分支——status=running
  时在存储对象上打 `runningSince: Date.now()`（UI 注入字段，终态事件整体
  替换后自然消失）。
- **类型**：`TaskStatusEvent` 补 `runningSince?: number`（注释注明
  UI-injected，后端不发）。
- **渲染**：TaskTreeSection running 行内 `task-tree-elapsed-<id>` 徽章，
  存在 running 任务时 1s tick（useEffect + setInterval，无 running 时清除）；
  格式 <60s `42s`、<1h `1m23s`、否则 `1h02m`。
- **测试**：orchestrationEvents 注入 1 例；TaskTreeSection 计时徽章渲染 +
  终态后消失 2 例（vi.useFakeTimestamp 控制 now）。

## 3. 批次 A 实施与验证记录

- **ingestion**：orchestrationEvents task_status 分支 running 事件打
  `runningSince: Date.now()`（UI 注入），终态事件整体替换自然消失。
- **类型**：TaskStatusEvent 补 `runningSince?`（注明 UI-injected）。
- **渲染**：TaskTreeSection running 行 `task-tree-elapsed-<id>` 徽章
  （formatElapsed：<60s 秒 / <1h 分秒 / 时分）；存在 running 任务时 1s
  setInterval tick，无 running 即清除。
- **测试**：orchestrationEvents 1 例（打点/终态消失）+ TaskTreeSection
  2 例（1m23s 格式与终态消失 / 亚分钟与无打点不渲染），24 例全绿。
- 验证：`tsc --noEmit` 干净；eslint 五个改动文件零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
