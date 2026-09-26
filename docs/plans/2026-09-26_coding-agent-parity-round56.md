# 编码代理对标差距分析·第五十六轮：时间线偏移负值防护（RD25）

- **状态**：批次 A 交付中（分支 `feat-event-timeline-now-r56`，基线 origin/main f8d9f6a2 = #1608）
- **上游文档**：R50（RD22 相对偏移引入）
- **对标对象**：N/A（bug 修复轮）

## 0. 结论速览

R50 引入的 `formatOffset` 未防护负偏移——生产者与消费者的时钟偏移可能导致
`occurred_at < base`，输出 `+-500ms` 等异常格式。本轮 clamp 到 0。

## 1. 差距矩阵

| # | 差距 | 证据 | 优先级 |
| --- | --- | --- | --- |
| RD25 | formatOffset 负值未防护 | `ms < 1000` 分支对负数输出 `+-Nms` | **P2** |

## 2. 设计（批次 A：RD25）

- `formatOffset` 首行加 `Math.max(0, ms)` clamp。

## 3. 批次 A 实施与验证记录

- **formatOffset**：首行加 `Math.max(0, ms)` clamp——时钟偏移导致
  `occurred_at < base` 时不再输出 `+-Nms`。
- **测试**：+1 例（负偏移 clamp 到 +0ms），3 例全绿；eslint 零告警。

## 4. 批次 B

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（交付后回填）
