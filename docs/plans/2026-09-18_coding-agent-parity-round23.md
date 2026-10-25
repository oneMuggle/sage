# 编码代理对标差距分析·第二十三轮：usage_events task_id 归因（2026-09-16）

- **状态**：批次 A 已交付（分支 `feat-parity-r23-batch-a`，基线 origin/main 58df53eb = #998）
- **上游文档**：round20（BU9/BU10 任务树消耗可见性）——本轮打通**按任务归因**的最后一环
- **对标对象**：Devin（ACU 按任务拆分）、Claude Code（TaskOutput 含 per-task token 计数）
- **编号约定**：延续 RT/BU 系

## 0. 结论速览

round20 BU9 让 task_status 事件携带 `used_tokens`（run 窗口累计），但 usage_events 表无 `task_id` 列——无法回答"哪个子任务花了多少 tokens"。本轮增列并打通归因管道。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT23 | usage_events 无 task_id 列 | `database.py` CREATE TABLE 无 task_id | Claude Code per-task token | **P1** |

## 2. 设计（批次 A：RT23）

- **schema**：`usage_events` 增 `task_id TEXT` 列（ALTER TABLE 迁移 + 索引）。
- **归因管道**：`usage_tracker.py` 增 `current_task_id` ContextVar + `set_current_task_id()` setter；`_persist` INSERT 自动携带（fail-open 不带）。
- **dispatcher**：任务启动时 `set_current_task_id(task_id)`，终态后清 None。
- **查询**：`task_usage_since(session_id, task_id, since_ms)` 方法。

## 3. 批次 A 实施与验证记录（2026-09-16）

- **schema**：`usage_events` 增 `task_id TEXT` 列（ALTER TABLE 迁移，旧列自动跳过）。
- **归因管道**：`usage_tracker.py` 增 `current_task_id` ContextVar + `set_current_task_id()` setter；`_persist` INSERT 自动携带 task_id（None → NULL，非编排路径无影响）。
- **查询**：`task_usage_since(session_id, task_id, since_ms)` 方法（fail-open 返 0）。
- **dispatcher**：`_run_one_inner` 任务启动前 `set_current_task_id(task_id)`，终态后清 None。
- 测试：ContextVar 归因 / task_usage_since / dispatcher 接线 6 例全绿；ruff 全过；收集 8404 零错误。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1049（squash `6f4a169d`，2026-09-17 16:32 UTC merge，CI 全绿）。
- **win7 对齐**：PR #1055（squash `51038fea`，2026-09-17 merge，py38 16m9s 全绿）。
- **对齐链路修证记录**（diff-patch 方式的三个踩坑，均为 CI 实证后修复）：
  1. `usage_tracker.py` PEP 604（`str | None`）→ py38 语法护栏拦截，改 `Optional[str]`；
  2. `_migrate_memory_traceability(conn)` 误置于 `init_db` 开头——新库首启时
     `memories_episodic` 尚未建表，`PRAGMA table_info` 返回空集后 `ALTER TABLE`
     报 "no such table"；移回建表之后（与旧版 205ca972 位置一致）；
  3. diff-patch 从 main 搬运 hunk 时误删 win7-only 的 `get_connection` 代理身份
     绑定（de9c6e250），`test_no_hook_emitted_on_failure` 故障注入落空
     （DID NOT RAISE）——按 `origin/release/win7` 整文件恢复后重放 RT23 hunk。
- **回填分支**：`docs/r23-backfill`（本提交）。
