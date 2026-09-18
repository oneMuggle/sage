# 编码代理对标差距分析·第二十八轮：守门状态透出到快照与部分聚合（BU14/BD8）

- **状态**：批次 A 交付中（分支 `feat-parity-r28-batch-a`，基线 origin/main 5cf8713a = #1157）
- **上游文档**：round11（BU2 预算守门）、round21（BU11 墙钟守门）、round17（BD6 collect 超时部分聚合）、round18（BD7 快照带 aggregate/budget_exceeded）
- **对标对象**：Devin（ACU 耗尽时明确告知已停）、Claude Code（MAX_THINKING/预算触顶可见）
- **编号约定**：延续 BU / BD 系

## 0. 结论速览

BD7 快照带 `budget_exceeded` 但缺 `wall_clock_exceeded`；BD6 collect 超时
部分聚合两者都不带——**预算/墙钟触顶后 conductor 拿到的 partial 载荷毫无
归因**，无法判断"任务没跑完是因为还在跑"还是"守门已停派"。本轮把两个
守门标志透出到快照与部分聚合，并在聚合文本中注入触顶说明行，使 conductor
在 LLM 语境里直接可见。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU14 | background_snapshot 缺 wall_clock_exceeded | dispatcher.py:503 只有 budget_exceeded | Devin 停止原因可见 | **P2** |
| BD8 | partial_aggregate 无守门归因 | dispatcher.py:530-535 仅 status/done/total/aggregate | Claude Code 预算文案 | **P2** |

## 2. 设计（批次 A：BU14 + BD8）

- **background_snapshot**：补 `wall_clock_exceeded` 键（与 budget_exceeded
  并列，fail-open 恒带键，bool）。
- **partial_aggregate**：载荷增 `budget_exceeded` / `wall_clock_exceeded`
  两键；任一触顶时在 aggregate 文本尾部追加说明行：
  `[预算已触顶，剩余任务已停止派发]` /
  `[墙钟上限已到，剩余任务已停止派发]`——conductor 的 LLM 语境直接可读。
- **测试**：快照双标志 1 例；partial 归因（预算触顶 / 墙钟触顶 / 未触顶
  无说明行）3 例。

## 3. 批次 A 实施与验证记录

- **background_snapshot**：补 `wall_clock_exceeded` 键（与 budget_exceeded
  对称，恒带键）。
- **partial_aggregate**：载荷增 `budget_exceeded` / `wall_clock_exceeded`
  两键；触顶时 aggregate 尾注入说明行（预算优先、互斥）：
  `[预算已触顶，剩余任务已停止派发]` / `[墙钟上限已到，剩余任务已停止派发]`。
- **测试**：test_chat_dispatcher_partial.py 3 例新增（预算触顶归因+快照对称 /
  墙钟触顶 / 未触顶零打扰）；既有 partial/r18/background 14 例无回归。
- 验证：partial+r18+background 17 例、budget+wall_clock 16 例全绿；
  ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
