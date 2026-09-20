# 编码代理对标差距分析·第二十六轮：编排设置全量收口（RD16）

- **状态**：批次 A 交付中（分支 `feat-parity-r26-batch-a`，基线 origin/main 37a7bd89 = #1105）
- **上游文档**：round25（RD15 三守门键透出）、P2 worktree 隔离模块
- **对标对象**：Cursor（agent 隔离/沙箱开关可见）、Claude Code（工作区隔离可配）
- **编号约定**：延续 RD 系

## 0. 结论速览

RD15 收口三个数值守门键后，编排设置仅剩两个后端早已生效但设置页无旋钮的键：
`worktreeIsolation`（P2 隔离层，dispatcher `_run_subagent` 接线，
worktree.py 提供临时 detached worktree 副本）与 `scratchRoot`
（dispatcher/orchestration_router 的 scratch 根目录名，默认 `orch_scratch`）。
本轮补齐后 **前端 OrchSettings 与后端 OrchSettings 键集完全对齐**。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD16-a | `worktreeIsolation` 无 UI 开关 | GeneralTab 无对应 Toggle；types/canonicalizer 已有键 | Cursor 隔离开关 | **P2** |
| RD16-b | `scratchRoot` 无 UI 输入 | 同上（文本键，默认 orch_scratch） | Claude Code 可配 | **P3** |

## 2. 设计（批次 A：RD16）

- **UI**：GeneralTab 编排 section 增：
  - SettingRow + Toggle「子任务 git worktree 隔离」
    （testId `orch-worktree-isolation`），desc 说明"仅隔离、不自动合并产物，
    git 不可用/非仓库自动降级 scratch 目录"；
  - 文本输入「Scratch 根目录名」（testId `orch-scratch-root`），沿用
    部分更新契约。
- **测试**：GeneralTab.orch.test.tsx 9→11 例（开关切换契约 + 文本输入契约 +
  默认值断言并入现有渲染用例）。
- 后端零改动（键已就绪）。

## 3. 批次 A 实施与验证记录

- **组件**：`components.tsx` ToggleProps 增可选 `testId`（渲染为
  `data-testid`，供测试锚定）；GeneralTab 增 `TextField` 局部组件
  （文本键部分更新契约，空白输入不提交）。
- **UI**：编排 section 末尾增「子任务 git worktree 隔离」Toggle
  （`orch-worktree-isolation`，desc 说明仅隔离不合并、失败自动降级）与
  「Scratch 根目录名」文本输入（`orch-scratch-root`）。
- **类型**：`OrchSettings` 补 `scratchRoot`（'orch_scratch'），
  DEFAULT_ORCH_SETTINGS 同步；更新 types.ts 中"scratchRoot 仅后端配置"
  的过时注释。storage 层为 DEFAULT spread 合并，新键天然透传。
- **测试**：GeneralTab.orch.test.tsx 9→11 例（开关切换契约 + 文本输入契约/
  空白防误提交 + 渲染用例补两个新锚点）。
- 验证：vitest 11 例全绿；`tsc --noEmit` 干净；eslint 改动文件零告警。
  后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1113（squash `04b9f3c7`，2026-09-18 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1117（squash `f1d91758`，2026-09-18 merge，py38 Win7 LTS
  16m 必过项全绿）。cherry-pick 干净落位，win7 基底 vitest 11 例本地全绿。
- **回填分支**：`docs/r26-backfill`（本提交）。
