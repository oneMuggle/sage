# 编码代理对标差距分析·第六十二轮：run 级聚合统计（RT27）

- **状态**：批次 A 交付中（分支 `feat-parity-r62`，基线 origin/main ac5c02a8 = #1727）
- **上游文档**：RT24（per-task used_tokens/duration_ms 持久化）
- **对标对象**：Devin（run 级 ACU 汇总）、Claude Code（会话总消耗）
- **编号约定**：延续 RT 系

## 0. 结论速览

`_run_detail` API 已透出 per-task used_tokens/duration_ms，但缺少 **run 级
汇总**——前端历史浏览器和 conductor 需逐任务累加才能得知总消耗/总时长。
本轮在 OrchRunDetail 增加 `total_used_tokens` / `total_duration_ms` 聚合
字段，一次请求即得全貌。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| RT27 | OrchRunDetail 无 run 级聚合统计 | `_run_detail` 无 total_used/total_dur | **P2** |

## 2. 设计（批次 A：RT27）

- OrchRunDetail 模型增 `total_used_tokens` / `total_duration_ms`。
- `_run_detail` 从 tasks 列表 `sum()` 聚合，零值/无终态任务时返回 None
  （不误导）。

## 3. 批次 A 实施与验证记录

- **backend/api/orch_routes.py**：OrchRunDetail 增两字段 + `_run_detail` 聚合。
- **测试**：+1 例（有终态任务 → 汇总正确；空任务 → None）。
- 验证：相关套件全绿；ruff 过。

## 4. 批次 B

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（交付后回填）
