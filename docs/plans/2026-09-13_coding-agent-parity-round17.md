# 编码代理对标差距分析·第十七轮：collect 超时的部分聚合返回（2026-09-13）

- **状态**：批次 A 已交付（分支 `feat-parity-r17-batch-a`，基线 origin/main 0d8a18e1 = #721）
- **上游文档**：round12（BD 系后台派发/收集）、round15（BD4 指令化）——本轮补收集侧的"超时不丢结果"
- **对标对象**：Claude Code（TaskOutput 超时返回已完成输出）
- **编号约定**：延续 BD 系
- **方法**：CollectSubagentsTool 超时路径核验，附 file:line

## 0. 结论速览

`collect_subagents(timeout_secs)` 超时路径目前只返回错误（`collect_timeout: …可再次 collect`），**已完成子任务的聚合结果随等待一并丢弃**——conductor 在长任务场景拿不到任何已完成产出，只能干等或放弃。Claude Code TaskOutput 超时会返回已完成输出。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BD6 | collect 超时不返回已完成聚合 | CollectSubagentsTool except TimeoutError → error（无结果载荷） | Claude Code TaskOutput | **P1** |

## 2. 设计（批次 A：BD6）

- `ChatDispatcher.partial_aggregate()`：基于当前 `_states` 调既有 `_aggregate()`，外层包 `{"status": "partial", "done", "total", "aggregate"}`。
- `wait_background` 超时路径不改签名；`CollectSubagentsTool` 捕获 `asyncio.TimeoutError` 后调 `partial_aggregate()` 返回 success 载荷（`status: "partial"` + 聚合文本 + note 提示可再次 collect 收全量）——conductor 拿到已完成产出并可决定提前汇总或继续等。
- 预算触顶/失败摘要已被 `_aggregate` 头部覆盖，无需重复。

## 3. 批次 A 实施与验证记录（2026-09-13）

- **BD6**：`ChatDispatcher.partial_aggregate()`（基于当前 `_states` 调既有 `_aggregate`，外层 `{status: "partial", done, total, aggregate}`；无在飞派发抛 RuntimeError）；`CollectSubagentsTool` 超时路径改返回 success 载荷——`status: "partial"` + 聚合文本（含已完成产出与失败摘要）+ note（`可稍后再次 collect_subagents 收取剩余结果，或据已完成部分提前汇总`）；无 `partial_aggregate` 能力的 dispatcher 回退旧错误文案。
- 测试：`test_chat_dispatcher_partial.py` 3 例（超时 partial 含快任务结果与进度计数、再 collect 收全量、无派发抛错、failed 计入 total 与聚合头失败摘要）；background/budget/retry_of 回归 20 passed；ruff 全过；收集 7111 零错误。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
