# 编码代理对标差距分析·第三十八轮：聚合头部消耗速率感知（BU21）

- **状态**：批次 A 交付中（分支 `feat-parity-r38-batch-a`，基线 origin/main 4cc8b3e6 = #1283）
- **上游文档**：round11（BU8）、round34（BU18 剩余额度）、总账优化建议 1
- **对标对象**：Devin（ACU 速率）、Claude Code（限流趋势提示）
- **编号约定**：延续 BU 系

## 0. 结论速览

预算行有总量与剩余，但**消耗速率**缺失——"剩余 200 tokens"在快速烧和
慢速烧下含义完全不同。本轮在预算行追加近 5 分钟消耗速率
`（近5分钟 R）`，conductor 可据趋势提前汇总（复用 session_usage_since
窗口参数，零新查询接口）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU21 | 聚合头部无消耗速率 | BU8/BU18 行仅总量/剩余 | Devin ACU 速率 | **P3** |

## 2. 设计（批次 A：BU21）

- **dispatcher**：BU8/BU18 预算行尾追加 `，近5分钟 R`——
  `session_usage_since(session_id, now-300_000)`；查询失败该段省略
  （fail-open 同 BU8）。
- **测试**：+1 例（预算行含近5分钟段；窗口外用量不计入 R）。

## 3. 批次 A 实施与验证记录

- **dispatcher**：BU8/BU18 预算行尾追加 `，近5分钟 R`——
  `session_usage_since(session_id, now-300s)`，try/except 失败省略该段
  （总量行不受影响）。
- **测试**：+1 例（速率段只含近 5 分钟用量；run 窗口本就排除更旧行），
  budget+partial 25 例全绿；ruff 全过。前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1287（squash `4ea6258a`，2026-09-19 merge，CI 12 项全绿）。
- **win7 对齐**：PR #1289（squash `7811674f`，2026-09-19 merge，win7 必过项
  全绿）。cherry-pick 干净落位，win7 基底 25 例本地全绿。
- **回填分支**：`docs/r38-parity-backfill`（本提交）。
