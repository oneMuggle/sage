# 编码代理对标差距分析·第二十五轮：编排设置可见性收口（RD15）

- **状态**：批次 A 交付中（分支 `feat-parity-r25-batch-a`，基线 origin/main b8d0010d = #1096）
- **上游文档**：round8（O2 任务超时）、round21（BU11 墙钟上限）、round22（RD14 重派链上限）
- **对标对象**：Claude Code（settings 可发现性）、Cursor（agent 超时/上限均可在 UI 配置）
- **编号约定**：延续 RD 系

## 0. 结论速览

round8/21/22 相继在后端交付了 `subagent_task_timeout_s`（默认 900）、
`run_wall_clock_limit_min`（默认 0=关）、`max_retry_of_chains`（默认 10）
三个守门键，但设置页从未透出——`settings.orch` 前端类型缺这三个键，
GeneralTab 编排 section 无对应输入。**后端有闸门、用户找不到旋钮**，
可发现性与 Claude Code / Cursor 的"上限皆可配"存在差距。本轮收口。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD15-a | 前端 `OrchSettings` 类型缺 3 键 | `entities/setting/types.ts` 无 runWallClockLimitMinutes / subagentTaskTimeoutS / maxRetryOfChains | Cursor UI 可配 | **P2** |
| RD15-b | 设置页编排 section 无对应输入 | `GeneralTab.tsx` 只有 6 个 NumberField | 同上 | **P2** |

## 2. 设计（批次 A：RD15）

- **类型**：`OrchSettings` 补 `runWallClockLimitMinutes`（0=关）、
  `subagentTaskTimeoutS`（900）、`maxRetryOfChains`（10），注释与后端
  `OrchSettings` 默认对齐；`DEFAULT_ORCH_SETTINGS` 同步补默认值。
- **UI**：编排 section 增三个 NumberField（沿用现有组件与 testid 命名）：
  - `orch-run-wall-clock-limit`「Run 墙钟上限（分钟，0=不限）」
  - `orch-subagent-task-timeout`「单子任务超时（秒，0=不限）」
  - `orch-max-retry-of-chains`「重派链上限（次）」
- **契约**：沿用部分更新语义 `updateSettings({ orch: { ...settings.orch, key: v } })`。
- 后端 `_RAW_KEYS` 三键已就绪（round21/22），无后端改动。

## 3. 批次 A 实施与验证记录

- **类型**：`OrchSettings` 补 `runWallClockLimitMinutes`（0）/`subagentTaskTimeoutS`
  （900）/`maxRetryOfChains`（10），注释注明上游轮次与后端默认对齐；
  `DEFAULT_ORCH_SETTINGS` 同步。
- **UI**：GeneralTab 编排 section 增三个 NumberField（`orch-run-wall-clock-limit` /
  `orch-subagent-task-timeout` / `orch-max-retry-of-chains`），部分更新契约不变。
- **测试**：GeneralTab.orch.test.tsx 6→9 例（默认值对齐 + 墙钟/超时/重派链
  部分更新契约）。
- 验证：vitest 9 例全绿；`tsc --noEmit` 干净；eslint 改动文件零告警。
  后端无改动（`_RAW_KEYS` 三键 round21/22 已就绪）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1099（squash `648a4aa7`，2026-09-18 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1104（squash `9ed8c28c`，2026-09-18 merge，必过项全绿）。
  cherry-pick 干净落位，win7 基底 vitest 9 例本地全绿。
- **回填分支**：`docs/r25-backfill`（本提交）。
