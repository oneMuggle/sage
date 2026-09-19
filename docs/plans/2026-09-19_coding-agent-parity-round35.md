# 编码代理对标差距分析·第三十五轮：子任务 Drawer 消耗/时长统计（RD19）

- **状态**：批次 A 交付中（分支 `feat-parity-r35-batch-a`，基线 origin/main 6a8eba0c = #1259）
- **上游文档**：round24（BU13 行内徽章）、round32（RT24 持久化）
- **对标对象**：Claude Code（Task 详情含 tokens/时长）
- **编号约定**：延续 RD 系

## 0. 结论速览

BU13/BU15 让任务树**行内**显示消耗/时长，但点击任务打开的
SubagentDetailDrawer 详情页没有这两项统计——详情比行内更贫瘠。
本轮：行内点击时把 `used_tokens`/`duration_ms` 一并传入
runControlStore（`selectTask` 增可选 meta），Drawer 头部渲染统计行。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD19 | Drawer 详情无消耗/时长统计 | SubagentDetailDrawer 头部仅状态/步骤 | Claude Code Task 详情 | **P3** |

## 2. 设计（批次 A：RD19）

- **store**：runControlStore 增 `selectedTaskMeta: { used_tokens?: number;
  duration_ms?: number } | null`；`selectTask(runId, taskId, meta?)` 第三参
  可选（缺省清空）——既有调用方零破坏。
- **TaskTreeSection**：`handleTaskClick` 透传 `{ used_tokens, duration_ms }`。
- **Drawer**：头部状态徽章下渲染统计行 `data-testid="drawer-task-stats"`
  （消耗 · 时长，值缺省不显）。
- **测试**：store meta 传递 1 例 + Drawer 渲染 1 例。

## 3. 批次 A 实施与验证记录

- **store**：runControlStore 增 `selectedTaskMeta`；`selectTask` 第三可选参
  （缺省清空），既有调用零破坏。
- **TaskTreeSection**：handleTaskClick 透传 `{ used_tokens, duration_ms }`。
- **Drawer**：头部下统计行 `drawer-task-stats`（消耗 tokens · 时长，自适应
  s/m+s/h+m，值缺省/全零不渲染）。
- **测试**：store meta 传递 1 例 + Drawer 渲染/缺省 2 例，相关套件 25+2 例
  全绿；`tsc --noEmit` 干净；eslint 改动文件零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1265（squash `e3f1d7a1`，2026-09-19 merge，CI 全绿）。
- **win7 对齐**：PR #1268（squash `fbbb2886`，2026-09-19 merge，win7 必过项
  全绿）。cherry-pick 干净落位，win7 基底 vitest 10 例本地全绿。
- **回填分支**：`docs/r35-backfill`（本提交）。
