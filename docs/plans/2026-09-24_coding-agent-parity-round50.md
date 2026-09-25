# 编码代理对标差距分析·第五十轮：事件时间线相对偏移（RD22）

- **状态**：批次 A 交付中（分支 `feat-event-timeline-r50`，基线 origin/main 2a26696c = #1534）
- **对标对象**：Cursor（步骤时间线相对偏移一目了然）
- **编号约定**：延续 RD 系

## 0. 结论速览

EventTimeline 事件时间线仅有绝对时间戳（HH:MM:SS），用户需心算才能得出
步骤间隔。本轮新增相对首事件的偏移列（+0ms / +500ms / +2.0s / +1m31s），
让耗时模式一目了然。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD22 | 时间线无相对偏移 | EventTimeline 仅 formatTime(occurred_at) | Cursor 步骤间隔 | **P3** |

## 2. 设计（批次 A：RD22）

- **formatOffset(ms)**：<1s 显 ms，<60s 显秒（1 位小数），≥60s 显分秒。
- **渲染**：时间戳右侧新增偏移列（`event-timeline-offset-<id>`，
  tabular-nums，主色标示），每行显示相对首事件的偏移。

## 3. 批次 A 实施与验证记录

- **EventTimeline.tsx**：`formatOffset` + 渲染偏移列（`visible[0]` 为基准）。
- **测试**：+2 例（ms/s 区间 + 跨分钟 m+s 格式），2 例全绿。
- 验证：`tsc --noEmit` 干净；eslint 改动文件零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
