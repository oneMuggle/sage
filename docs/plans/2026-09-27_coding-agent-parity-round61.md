# 编码代理对标差距分析·第六十一轮：per-agent token 分布 + 负偏移防护

- **状态**：批次 A 交付中（分支 `feat-parity-r61`，基线 origin/main 9ad0b9a7）
- **上游文档**：R38（BU21 消耗速率）、R50（RD22 偏移）
- **对标对象**：Devin（ACU 按 agent 拆分）
- **编号约定**：延续 BU/RD 系

## 0. 结论速览

聚合头部 BU23 已有任务数量分布但无 **per-agent token 分布**——conductor
无法判断哪个 agent 烧得多。同时 formatOffset 存在负偏移未防护的 bug。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| BU24 | 聚合头部无 per-agent token 分布 | 仅 BU23 任务数量分布 | **P2** |
| RD25 | formatOffset 负偏移未防护 | `+-Nms` 异常输出 | **P2** |

## 2. 设计

- BU24：BU23 后追加 `Agent token 分布：primary×1000、researcher×500。`
- RD25：`formatOffset` clamp 负偏移到 0。

## 3. 批次 A 实施与验证记录

- BU24：`_aggregate` BU23 后追加 `_agent_tokens` 聚合（复用 `_task_tokens_used` memoize）。
- RD25：`formatOffset` 首行 `Math.max(0, ms)` clamp。
- 测试：BU24 +2 例、RD25 +1 例；budget+partial+doctor+events 全绿。

## 4. 批次 B

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（交付后回填）
