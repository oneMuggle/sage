# 编码代理对标差距分析·第三十一轮：聚合块任务级消耗标注（BU17）

- **状态**：批次 A 交付中（分支 `feat-parity-r31-batch-a`，基线 origin/main 676e0953 = #1185）
- **上游文档**：round23（RT23 task_id 归因）、round24（BU13 per-task 事件）、round11（BU8 头部消耗行）
- **对标对象**：Claude Code（Task 结果含 token 计数）、Devin（ACU 按步骤拆分）
- **编号约定**：延续 BU 系

## 0. 结论速览

BU13 让前端事件带 per-task tokens，但 **conductor 收到的聚合文本块没有任务
级消耗**——LLM 判断"哪个子任务代价过高/是否值得重试"时无量化依据。
本轮在每个终态子任务块标题追加 `（消耗 N tokens）`（RT23 归因查询 +
run 内 memoize，预算关闭也可用，查询 fail-open 跳过）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU17 | 聚合块无任务级 token 标注 | `_aggregate` 块标题仅 task_id/agent_id/状态 | Claude Code per-Task tokens | **P3** |

## 2. 设计（批次 A：BU17）

- **dispatcher**：新增 `_task_tokens` memo dict 与
  `_task_tokens_used(task_id)`（`task_usage_since`，since=run 首派发；
  查询失败返 None 不缓存；终态后缓存不更新——token 计数终态即定格）。
- **`_aggregate`**：终态块标题追加 `（消耗 N tokens）`（N>0 才显；
  preset 回放任务查询得 0 不显）。
- **测试**：3 例（done 块带消耗行 / 未产生用量任务不显 / memo 二次聚合
  不再查询）。

## 3. 批次 A 实施与验证记录

- **dispatcher**：`_task_tokens` memo dict + `_task_tokens_used()`
  （`task_usage_since`，since=run 首派发；失败返 None 不缓存）；
  `_aggregate` 终态块标题追加 `（消耗 N tokens）`（N>0 才显；仅终态块
  查询——running 块查询会缓存滞后值；preset 回放 0 不显）。
- **测试**：+2 例（done 块消耗行 + 无用量任务不显 / memo 二次聚合零查询
  ——dispatch 末尾聚合会预热 memo，断言前清空计量）。
- 验证：budget+partial 20 例全绿；ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
