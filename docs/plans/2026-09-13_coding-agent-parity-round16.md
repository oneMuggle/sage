# 编码代理对标差距分析·第十六轮：预算语义收口与后台工作流策略补全（2026-09-13）

- **状态**：批次 A 已交付（分支 `feat-parity-r16-batch-a`，基线 origin/main 93e66070 = #715）
- **上游文档**：round11（BU 系预算守门已交付）、round12/15（BD 系后台派发/收集/指令化已交付）——本轮收口两者交界处的语义粗糙面
- **对标对象**：Devin（预算触顶的任务级归因）、Claude Code（后台代理的部分结果策略）
- **编号约定**：延续 BU/BD 系
- **方法**：预算触顶路径与后台工作流指引的边界核验，附 file:line

## 0. 结论速览

1. **BU6 预算触顶的任务级归因失真**：预算触发 `_cancelled.set()` 后，同批 queued 任务经 merged 守卫收口时 error 一律写 `cancelled by user`（`chat_dispatcher.py` merged 守卫）——但触顶并非用户操作，任务树/事件里的归因误导排障。round11 仅在聚合头部标注，任务级 error 文案未区分。
2. **BD5 collect 快照策略未指令化**：BD4 指令讲了 background/collect 等待语义，但未讲 `wait=false` 非阻塞快照的用途——conductor 在"已有足够信息提前汇总"决策点上缺少策略指引。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU6 | 预算触顶收口的任务 error = `cancelled by user`，归因失真 | `_run_one_inner` merged 守卫（error 二选一：cancelled by user / skipped by user，无预算分支） | Devin 预算任务归因 | **P2** |
| BD5 | collect 非阻塞快照策略未进 conductor 指令 | BD4 指令仅述等待语义 | Claude Code TaskOutput 策略指引 | P2 |

## 2. 设计（批次 A：BU6+BD5）

- **BU6**：merged 守卫收口时，若 `self._budget_exceeded` → error = `budget_exceeded: 本 run token 预算（N）已耗尽`（与 dispatch 入口拒绝的 `budget_exceeded` 前缀一致，前端/排障可 grep）；用户取消仍为 `cancelled by user`，跳过仍为 `skipped by user`——三者互斥，优先级：用户取消 > 预算 > 跳过（保持既有判断顺序语义，仅在非用户取消分支细分）。
- **BD5**：BD4 指令追加一句——collect 可传 `wait=false` 立即获取各任务当前状态与结果预览快照，用于判断"已有信息是否足够提前汇总"。

## 3. 批次 A 实施与验证记录

（实施后回填）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
