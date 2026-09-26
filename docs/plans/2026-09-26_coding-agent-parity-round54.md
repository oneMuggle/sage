# 编码代理对标差距分析·第五十四轮：历史编排行内消耗统计（RD24）

- **状态**：批次 A 交付中（分支 `feat-parity-r54-batch-a`，基线 origin/main 93d2ffa2 = #1598）
- **上游文档**：R52（RD23 SessionRunHistory 组件）、R32（RT24 持久化）
- **对标对象**：Devin（会话历史 ACU 统计）
- **编号约定**：延续 RD 系

## 0. 结论速览

R52 的 `SessionRunHistory` 组件展示历史 run 列表（状态/目标/进度/时间）
但不显示**run 级消耗统计**。RT24 持久化了 `used_tokens`/`duration_ms`
且 `_run_detail` API 已透出。本轮在历史行内追加消耗汇总（所有任务
used_tokens 之和）与已完成进度。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD24 | 历史行内无消耗统计 | SessionRunHistory 行仅状态/目标/进度/时间 | Devin ACU 汇总 | **P3** |

## 2. 设计（批次 A：RD24）

- **SessionRunHistory**：从 `run.tasks` 聚合 `used_tokens` 总和与
  `duration_ms` 总和，行内追加 `· N tokens`（N>0 才显）和 `· T 总耗时`。

## 3. 批次 A 实施与验证记录

- **SessionRunHistory**：每行追加 run 级消耗汇总（`reduce` 聚合
  `tasks[].used_tokens`，N>0 才显 `N tokens`）。
- **验证**：tsc 零新增错误；eslint 零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1604（squash `2d35a77d`，CI 14 项全绿）。
- **win7 对齐**：PR #1607（squash `783f4a66`，win7 必过项全绿）。
- **回填分支**：`docs/r54-parity-backfill`（本提交）。
