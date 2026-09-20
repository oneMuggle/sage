# 编码代理对标差距分析·第四十二轮：run 触顶原因横幅（RD21）

- **状态**：批次 A 交付中（分支 `feat-parity-r42-batch-a`，基线 origin/main 8e8a9b2f = #1303）
- **上游文档**：round16（BU6 归因前缀）、round34（BU18 conductor 侧归因行）
- **对标对象**：Devin（ACU 耗尽的用户侧明确提示）
- **编号约定**：延续 RD 系

## 0. 结论速览

预算/墙钟触顶后，用户侧任务树只见一排 cancelled——**为什么停**仍然藏在
被取消任务的 error 文本里（`budget_exceeded:` / `wall_clock_exceeded:`
前缀）。本轮在任务树顶部渲染触顶原因横幅（RD20 语义的前端面），
与 R38 的 conductor 侧归因行互补。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD21 | 用户侧无 run 触顶原因横幅 | TaskTreeSection 无 trip-reason 渲染 | Devin 停止提示 | **P3** |

## 2. 设计（批次 A：RD21）

- **TaskTreeSection**：扫描 `board.statuses` 中带
  `budget_exceeded:` / `wall_clock_exceeded:` error 前缀的任务，
  在进度行下渲染 `task-tree-trip-reason` 横幅：
  「⚠ 预算已触顶，剩余任务已停止派发」/「⚠ 墙钟上限已到，剩余任务已停止
  派发」（预算优先，与后端 `_aggregate` 措辞一致）。
- **测试**：+2 例（两类横幅 / 普通取消不渲染）。

## 3. 批次 A 实施与验证记录

- **TaskTreeSection**：`tripReason` useMemo 扫描 `board.statuses` 的 error
  前缀（`budget_exceeded:` 优先于 `wall_clock_exceeded:`，与后端聚合措辞
  一致），进度行下渲染 `task-tree-trip-reason` 横幅；无守门前缀不渲染。
- **测试**：+2 例（预算横幅优先 / 墙钟横幅 + 普通失败不渲染），文件
  19 例全绿。
- 验证：`tsc --noEmit` 干净；eslint 改动文件零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1306（squash `58d7b19e`，2026-09-19 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1312（squash `ce086aff`，2026-09-19 merge，win7 必过项
  全绿）。含与并行 RD18 测试同文件的合并解决；win7 基底 vitest 19 例本地全绿。
- **回填分支**：`docs/r42-parity-backfill`（本提交）。
