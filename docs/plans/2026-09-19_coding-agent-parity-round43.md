# 编码代理对标差距分析·第四十三轮：历史编排 run 恢复增强（RD20）

- **状态**：批次 A 交付中（分支 `feat-parity-r43-batch-a`，基线 origin/main 78f1b6f5 = #1316）
- **上游文档**：round32（RT24 orch_tasks 用量/时长持久化）、round34（BU16 run 耗时）
- **对标对象**：Claude Code（会话历史含每 Task tokens/时长）、Devin（历史 ACU）
- **编号约定**：延续 RD 系

## 0. 结论速览

C1 通道已能恢复会话最近一次编排 run 的任务板，但恢复映射丢掉了 RT24 的
`used_tokens` / `duration_ms`——**历史任务树退化成纯状态列表**，量化数据
落库了却没人消费。本轮：恢复映射补齐两字段 + `endedAt`（run 终态时刻，
BU16 恢复态显示原始总时长而非"从恢复时刻起算"），映射逻辑抽取为纯函数
`restoreRunToBoard`（可单测）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD20 | 历史恢复丢 used_tokens/duration_ms；无 endedAt | Chat.tsx 恢复映射缺字段 | Claude Code 历史 | **P3** |

## 2. 设计（批次 A：RD20）

- **抽取**：`orchestrationEvents.ts` 新增纯函数 `restoreRunToBoard(run:
  OrchRunDetail)`：statuses/progress/plan 反推 + `used_tokens`/
  `duration_ms` 映射 + `endedAt = max(task.finished_at)`；无任务返回 null。
- **Chat.tsx**：恢复 useEffect 改调该函数（含空 plan 反推逻辑一并迁移）。
- **类型/store**：`TaskBoardState` 增 `endedAt?: number | null`。
- **TaskTreeSection**：BU16 行 elapsed 取 `(board.endedAt ?? now) -
  dispatchedAt`——恢复态冻结为原始总时长，直播态仍实时 tick。
- **测试**：restoreRunToBoard 1 例（字段映射/endedAt/空任务）；BU16 恢复态
  冻结 1 例。

## 3. 批次 A 实施与验证记录

- **orchestrationEvents.ts**：新增纯函数 `restoreRunToBoard(run)`——
  statuses/progress/plan 反推 + RT24 `used_tokens`/`duration_ms` 映射 +
  `endedAt = max(task.finished_at)`；空任务 run 返回 null。
- **Chat.tsx**：恢复 useEffect 改调该函数（内联映射整体迁移，含空 plan
  反推）；board 写入 `endedAt`。
- **store**：`TaskBoardState` 增 `endedAt?: number | null`。
- **TaskTreeSection**：BU16 行 elapsed 取 `(board.endedAt ?? now) -
  dispatchedAt`——恢复态冻结为原始总时长，直播态仍实时 tick。
- **测试**：restoreRunToBoard 2 例（字段映射/endedAt/空任务）+ BU16 恢复
  冻结 1 例，相关套件 37 例全绿；`tsc --noEmit` 干净；eslint 六文件零告警。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1376（squash `ed3d546d`，2026-09-20 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1379（squash `a7124d15`，2026-09-20 merge，win7 必过项
  全绿）。Chat.tsx 导入冲突按 HEAD 侧落位（win7 无
  useFileUpload/CHAT_DOCUMENT_EXTENSIONS）；win7 基底 vitest 37 例本地全绿。
- **回填分支**：`docs/r43-parity-backfill`（本提交）。
