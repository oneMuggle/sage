# 编码代理对标差距分析·第三十二轮：编排任务持久化携带用量与时长（RT24）

- **状态**：批次 A 交付中（分支 `feat-parity-r32-batch-a`，基线 origin/main dca62715 = #1191）
- **上游文档**：round23（RT23 usage_events.task_id 归因）、round17（BU13 前端事件）
- **对标对象**：Claude Code（会话历史含每 Task tokens）、Devin（历史按步骤 ACU）
- **编号约定**：延续 RT 系

## 0. 结论速览

`orch_tasks` 表（run 历史的数据源）只有状态/预览/起止时间——**run 结束后
任务板清空，历史回看无任何量化数据**。本轮给 orch_tasks 增 `used_tokens` /
`duration_ms` 两列：终态落库时由 dispatcher 复用 BU17 的 memo 查询与时長
计算写入，`GET /orch/runs/{id}` 详情透出，历史回看有据可查。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT24 | orch_tasks 无用量/时长列；API 不透出 | upsert_state 参数表无；`_run_detail` tasks 无 | Claude Code/Devin 历史 | **P3** |

## 2. 设计（批次 A：RT24）

- **schema**：orch_tasks 增 `used_tokens INTEGER` / `duration_ms INTEGER`
  （ALTER TABLE 迁移，存在即跳过）。
- **repo**：`upsert_state` 增两参，INSERT/UPDATE 同步。
- **dispatcher**：`_persist_task_state` 终态时传 `_task_tokens_used()`
  （BU17 memo）与 `duration_ms`（started/finished 差）；非终态传 None。
- **API**：`_run_detail` 的 tasks 元素带 `used_tokens` / `duration_ms`。
- **测试**：repo 往返 1 例 + dispatcher 终态落库 1 例 + API 详情字段 1 例。

## 3. 批次 A 实施与验证记录

- **schema**：orch_tasks 增 `used_tokens INTEGER` / `duration_ms INTEGER`
  （revision 迁移同位幂等 ALTER）。
- **repo**：`upsert_state` 增两参并 INSERT/UPDATE 同步；`OrchTask` 补两字段；
  `_row_to_task` 以 `row.keys()` 列集防御旧库缺列（顺带修 revision 同款
  SIM118）。
- **dispatcher**：`_persist_task_state` 终态传 `_task_tokens_used()`（BU17
  memo）与 duration_ms（started/finished 差）；非终态 None。
- **API**：`_run_detail` tasks 带 `used_tokens` / `duration_ms`。
- **测试**：+1 例（dispatcher 终态落库 + API 详情透出；orch_runs 外键先
  落 run 行），budget+rerun+partial 31 例全绿；ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
