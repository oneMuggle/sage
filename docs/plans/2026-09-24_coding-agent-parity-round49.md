# 编码代理对标差距分析·第四十九轮：重派链历史持久化（RT26）

- **状态**：批次 A 交付中（分支 `feat-parity-r49-batch-a`，基线 origin/main ebf58081 = #1477）
- **上游文档**：round22（RD14 重派链上限）、round33（RD18 根因徽章）、round43（RD20 恢复增强）
- **对标对象**：Devin/Claude Code（会话历史含重做/重派标注）
- **编号约定**：延续 RT 系

## 0. 结论速览

RD13+ 的 `retry_of`（重派来源）仅存在于内存 ChatTaskState——orch_tasks
表不持久化、恢复映射不映射，**历史任务树无法显示"重派"徽章**。
本轮补齐持久化 + 恢复映射全链路（与 RT24 的 used_tokens/duration_ms
同一模式）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RT26 | orch_tasks 无 retry_of 列；恢复任务树丢"重派"徽章 | orch_task_repo 无 retry_of；restoreRunToBoard 无映射 | Devin 重做标注 | **P3** |

## 2. 设计（批次 A：RT26）

- **schema**：orch_tasks 增 `retry_of TEXT`（幂等 ALTER）。
- **repo**：`upsert_state` 增 `retry_of` 参数；`OrchTask` 补字段；
  `_row_to_task` 防御旧库缺列。
- **dispatcher**：`_persist_task_state` 传 `state.retry_of`。
- **API**：`_run_detail` tasks 透出 `retry_of`。
- **前端**：`restoreRunToBoard` 映射 `retry_of` → 历史任务树"重派"徽章。
- **测试**：持久化 + 恢复映射 + API 透出。

## 3. 批次 A 实施与验证记录

- **schema**：orch_tasks 增 `retry_of TEXT`（幂等 ALTER，置于 depth ALTER
  之后——orch_tasks 表创建后的同区域）。
- **repo**：`upsert_state`/`OrchTask`/`_row_to_task` 同步（列集防御旧库缺列）。
- **dispatcher**：`_persist_task_state` 传 `state.retry_of`。
- **API**：`_run_detail` tasks 透出 `retry_of`。
- **前端**：`restoreRunToBoard` 映射 `retry_of` → 恢复任务树"重派"徽章。
- **测试**：后端 +1 例（持久化往返），前端 +1 例（retry_of 恢复）；
  budget 21 例全绿、events 18 例全绿；ruff 全过。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
