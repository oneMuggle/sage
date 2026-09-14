# 编码代理对标差距分析·第十九轮：聚合头部消耗可见性（2026-09-14）

- **状态**：批次 A 已交付（分支 `feat-parity-r19-batch-a`，基线 origin/main 3af4a37e = #764）
- **上游文档**：round11（BU2 守门）、round16（BU6 归因）、round18（BU7 预警）——本轮补预算叙事的最后一块：**进行中的可见性**
- **对标对象**：Devin（ACU 进度可见）、Claude Code（/cost）
- **编号约定**：延续 BU 系
- **方法**：_aggregate 头部与 usage 查询路径核验

## 0. 结论速览

预算生命周期现状：80% 预警（BU7 日志）→ 触顶收口（BU2）→ 触顶归因（BU6）→ 聚合头部触顶标注（round11）。缺口：**进行中/完成态的聚合头部不展示"已消耗多少 tokens"**——conductor 决定"是否提前汇总"时看不到量化依据，用户在任务板上也看不到。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU8 | 聚合头部无消耗行（预算开启时） | `_aggregate` 头部仅有进度/失败/取消/触顶标注 | Devin ACU 进度 | **P2** |

## 2. 设计（批次 A：BU8）

- `_aggregate` 头部在 `run_token_budget > 0` 且 `session_id`/`_first_dispatch_at` 就绪时追加一行：`- 已消耗 X / 预算 M tokens（P%）`；触顶后沿用既有预算标注（不重复）。
- 消耗查询复用 `UsageTracker.session_usage_since`（fail-open 返 0，不阻塞聚合）。

## 3. 批次 A 实施与验证记录（2026-09-15）

- **BU8**：`_aggregate` 头部在 `run_token_budget > 0` 且 session 归因就绪时追加 `- 已消耗 X / 预算 M tokens（P%）` 行；fail-open（查询失败跳过该行）；预算关闭时不展示。触顶态沿用既有 ⚠ 标注（不重复展示消耗行）。
- 测试：`test_chat_dispatcher_bu8.py` 2 例（预算开启展示消耗行 / 关闭无行）；budget/partial/retry_of/background 回归 23 passed；ruff 全过；收集 7287 零错误。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（聚合头部消耗可见性） | PR #770（squash 2a3c32d7） | PR #776（cherry-win7-r19，squash aa146168） |

win7 对齐说明：零冲突落位；py3.8 纪律照旧；本地 ruff 全过 + bu8 2 例绿后由 CI（含 py3.8 job）终验，squash merge（#776）。
