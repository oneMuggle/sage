# 编码代理对标差距分析·第五十一轮：cancel 时清理待决审批（OPS4）

- **状态**：批次 A 交付中（分支 `feat-ops4-approval-cleanup-r51`，基线 origin/main 8a08428b = #1556）
- **上游文档**：DSH-R6 审批闸口（`_pending_approvals`）、round22（RD14 重派链上限）
- **对标对象**：VS Code doctor / Claude Code（cancel 后不泄露 pending 状态）
- **编号约定**：OPS 系（流程自动化/健壮性）

## 0. 结论速览

run 取消（cancel）时 `_pending_approvals` 字典不清空——已撤销的审批请求
仍留在 dict 中，后续 `resolve_approval` 调用会误返回 True（看似"命中"），
且造成状态泄露。本轮在 cancel 中清空 `_pending_approvals` 并标注原因。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| OPS4 | cancel 不清理 `_pending_approvals` | cancel() 方法无相关逻辑 | VS Code doctor | **P2** |

## 2. 设计（批次 A：OPS4）

- **cancel()**：置位取消事件后，若 `_pending_approvals` 非空则 `clear()`
  （并 debug 日志记录清理数量）。
- **测试**：+2 例 ——
  1. 有待决审批时 cancel → dict 被清空；
  2. cancel 后 `resolve_approval` 返回 False（不再误命中）。

## 3. 批次 A 实施与验证记录

- **cancel()**：置位取消事件后清空 `_pending_approvals`（debug 日志记录
  清理数量）；已 set 幂等路径不重复清理。
- **测试**：+2 例（cancel 后 dict 清空 / cancel 后 resolve_approval 返回
  False），budget 套件 23 例全绿；ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
