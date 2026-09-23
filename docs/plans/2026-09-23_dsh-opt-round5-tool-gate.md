# DSH 对标优化·第五轮：分发前门控链抽离（GT1）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r5-tool-gate`，基线 origin/main 612579e7）
- **系列定位**：`dsh-opt` 对标系列第 5 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round3（B2 并行调度，main #1451 / win7 #1459）、
  round4（TM1 计量，main #1462 / win7 #1466）
- **对标对象**：DeepSeek Harness 工具五段管线的第一段
  （`tools/pre-execute` waterfall：allow/deny/cancel/ask）——策略判定
  是可组合的监听者，不是 loop 内联代码。

## 0. 结论速览

B2 完成调度分组后，串行管线里仍有约 50 行门控策略内联在 run_loop
（profile 白名单 → M1 enforcer → S3 自动放行台账）。本轮抽成
`SageAgent._pre_dispatch_gate(tc, args, enforcer, session_id)` 单元方法，
行为逐条保持（含"白名单拒绝时 enforcer.check 仍被调用"的既有副作用
顺序）。审批闸口（PERMISSION_REQUEST yield + await）含事件/异步语义，
本轮留在 run_loop，GT2 再收——五段管线方向的第一刀。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| GT1 | 分发前门控策略内联 run_loop，不可单测不可组合 | agent.py 白名单/enforcer/台账三段内联 | dsh pre-execute waterfall 监听者 | **P2** |

## 2. 设计（批次 A：GT1）

- `_pre_dispatch_gate(tc, args, enforcer, session_id) ->
  (PermissionDecision, denial_content)`：
  1. profile 白名单执行边界再校验（拒绝 → warning + denial_content）；
  2. M1 `enforcer.check`——**白名单拒绝时仍调用**（保留既有副作用顺序），
     随后覆盖判定；
  3. S3 自动放行台账——仅免审放行记录，fail-safe。
- run_loop 侧：三分支替换为 `(decision, denial_content) = self.
  _pre_dispatch_gate(...)`；审批闸口与拒绝文案组装保持原位（语义零变更）。

## 3. 批次 A 实施与验证记录

（实施后回填）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
- **历史轮次回填（随本轮入总账）**：
  - R3 win7：PR #1459（squash `c3feb150`，2026-09-23 merge，py38 全量
    绿；agent.py 结构移植脚本化完成，win7 独有代码零丢失）
  - R4：main #1462（`d545bb1f`）/ win7 #1466（`bd35e989`）
