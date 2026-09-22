# 编码代理对标差距分析·第四十六轮：任务归因查询索引（RT25）

- **状态**：批次 A 交付中（分支 `feat-parity-r46-batch-a`，基线 origin/main 54af0ee0 = #1404）
- **上游文档**：round23（RT23 task_id 归因）、round24（BU13 per-task 查询）、round31（BU17 聚合块标注）
- **对标对象**：Cursor/Devin（用量查询随历史增长保持 O(log n)）
- **编号约定**：延续 RT 系

## 0. 结论速览

BU13（事件）与 BU17（聚合）每个终态任务都会调 `task_usage_since`
（`WHERE session_id = ? AND task_id = ? AND created_at >= ?`），但
usage_events 仅有 `(session_id, created_at)` 与 `(created_at)` 两个索引
——task_id 过滤退化为 session 内全行扫描，随历史增长每轮聚合成本线性
上升。本轮补 `(session_id, task_id, created_at)` 复合索引。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT25 | task_id 过滤无索引支撑 | EXPLAIN QUERY PLAN 未命中索引 | 任意规模可查 | **P2** |

## 2. 设计（批次 A：RT25）

- **schema**：`CREATE INDEX IF NOT EXISTS idx_usage_events_session_task
  ON usage_events(session_id, task_id, created_at)`（幂等，旧库自动补建）。
- **测试**：+1 例 —— init_db 后 `EXPLAIN QUERY PLAN` 断言命中新索引
  （杜绝退化为 SCAN）。

## 3. 批次 A 实施与验证记录

- **首次落位踩坑**：索引最初写在 usage_events 索引块（表创建处）——旧库
  首次 init_db 时 task_id 列要到 RT23 ALTER（文件更靠后）才补上，
  CREATE INDEX 直接报 no such column。已移至 RT23 ALTER 之后，
  新旧库双路径均安全。
- **schema**：`idx_usage_events_session_task ON usage_events(session_id,
  task_id, created_at)`（幂等）。
- **测试**：+1 例 —— PRAGMA index_list 断言索引存在 + EXPLAIN QUERY PLAN
  断言 task_usage_since 的查询命中该索引（杜绝退化 SCAN）。
- 验证：budget 20 例全绿；ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
