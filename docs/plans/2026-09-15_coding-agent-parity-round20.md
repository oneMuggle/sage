# 编码代理对标差距分析·第二十轮：预算消耗在任务树的实时可见性（2026-09-14）

- **状态**：批次 A 已交付（分支 `feat-parity-r20-batch-a`，基线 origin/main 2324dcba = #833）
- **上游文档**：round11（BU2 守门）、round16（BU6 归因）、round18（BU7 预警）、round19（BU8 聚合头部消耗行）——本轮把预算叙事推向**实时 UI**：预算消耗在任务树上的持续可见
- **对标对象**：Devin（ACU 进度条实时更新）、Claude Code（后台代理进度可观测）
- **编号约定**：延续 BU 系
- **方法**：事件面/任务板/消耗查询路径核验，附 file:line

## 0. 结论速览

预算叙事现状：80% 预警（BU7 日志）→ 触顶收口（BU2）→ 触顶归因（BU6）→ 聚合头部消耗行（BU8，仅 conductor 上下文）。缺口：**任务树/前端在 run 进行中看不到实时消耗**——用户要等聚合返回才知道花了多少。Claude Code 后台代理进度实时可观测。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU9 | 任务树无实时消耗行（预算开启时） | `_emit_task_status` 事件无用量字段；TaskTreeSection 无消耗 UI | Devin ACU 进度条 | **P2** |
| BU10 | task_progress 事件无消耗聚合 | `chat_dispatcher.py` `_emit_task_progress`（若存在）同样无用量字段 | 同上 | P2 |

## 2. 设计（批次 A：BU9+BU10）

- **BU9**：dispatcher 增 `_current_usage()` 辅助（复用 `session_usage_since`）；`_emit_task_status` 事件增 `used_tokens` 字段（预算开启且归因就绪时携带，None 不带键）；`TaskStatusEvent` 类型扩展。
- **BU10**：TaskTreeSection 进度行追加消耗显示（`已消耗 N tokens`，预算开启时 `N / M`）——数据源 task_progress 事件增 `used_tokens` 字段。
- fail-open：查询失败不带字段。

## 3. 批次 A 实施与验证记录

（实施后回填）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）
