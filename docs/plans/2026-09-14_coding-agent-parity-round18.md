# 编码代理对标差距分析·第十八轮：快照聚合增强与预算预警（2026-09-14）

- **状态**：批次 A 已交付（分支 `feat-parity-r18-batch-a`，基线 origin/main 2982dfb9 = #742）
- **上游文档**：round11（BU 系预算守门）、round12/13（BD 系后台派发/收集/快照）——本轮深化两者的联动缺口
- **对标对象**：Claude Code（后台代理中途可观测）、Devin（预算进度可见）
- **编号约定**：延续 BD/BU 系
- **方法**：后台快照/预算守门路径核验，附 file:line

## 0. 结论速览

1. **BD7 非阻塞快照缺聚合预览**：`collect_subagents(wait=false)` 返回的 `background_snapshot()`（`chat_dispatcher.py:379-399`）只有任务状态清单，**不含部分聚合文本**——conductor 想在不阻塞的前提下了解"目前已完成了什么"，只能等 collect 阻塞返回。而超时路径（BD6）反而有完整聚合。快照与部分聚合能力不对称。
2. **BU7 预算无预警**：预算守门只在 100% 触顶时收口（`_check_run_budget`），触顶前无任何预警——用户与 conductor 都是"突然被停"。缺一个 80% 跨越点的一次性预警。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BD7 | wait=false 快照无聚合预览 | `background_snapshot` 返回 `{status, tasks[]}`，无 aggregate 字段 | Claude Code TaskOutput 可见部分输出 | **P2** |
| BU7 | 预算无 80% 预警 | `_check_run_budget` 仅 `used > budget` 二值判断 | Devin 预算进度 | P2 |

## 2. 设计（批次 A：BD7+BU7）

- **BD7**：`background_snapshot()` 增 `aggregate` 字段（当前 `_states` 调既有 `_aggregate`，与 `partial_aggregate` 同源）与 `budget_exceeded` 标志——wait=false 快照即刻可见"已完成什么 + 是否触顶"。
- **BU7**：`_check_run_budget` 增 80% 跨越点一次性预警（`_budget_warned` 标志防重复）：WARNING 日志 + `_aggregate` 头部在预警态追加"接近预算"提示（仅超限后改为触顶文案，既有逻辑）。

## 3. 批次 A 实施与验证记录

（实施后回填）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（快照聚合增强与预算预警） | PR #750（squash cde9bd89） | PR #753（cherry-win7-r18，squash 2a15be83） |

win7 对齐说明：零冲突落位；py3.8 纪律照旧；本地 ruff 全过 + r18 4 例绿后由 CI（含 py3.8 job）终验，squash merge（#753）。
