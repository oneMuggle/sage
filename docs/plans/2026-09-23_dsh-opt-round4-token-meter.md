# DSH 对标优化·第四轮：上下文压力计量（TM1，后端薄片）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r4-tool-gate`，基线 origin/main 8b27eaf6）
- **系列定位**：`dsh-opt` 对标系列第 4 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round1（SE1）、round2（SE2）、round3（B2）
- **对标对象**：DeepSeek Harness `token-meter`——重放持久日志做确定性
  估算，输出 tokenUsage / contextPressure / contextBreakdown；容量上限
  来自 model catalog。

## 0. 结论速览

sage 的上下文预算逻辑四处独立且只有单一总数（history 预算、工具结果
截断、run 级水位、first-aid 压缩），没有任何一处回答"当前请求用了多少
上下文、各部分占多少、离窗口上限还有多远"。本轮新增统一计量模块：

- `ContextPressure`：total / by_role（system/user/assistant/tool）
  / budget / pressure(0-1)；
- 估算口径复用 `estimate_messages_tokens`（与 WorkingMemory、compaction
  同源，**不改任何阈值行为**）；
- producer 装配请求后记一条结构化 INFO 日志（含 breakdown 与 pressure），
  为后续 UI 状态栏（TM2）与按路径性能预算（D 系列）提供数据源。

本轮为纯增量：不改事件协议、不改前端、不改预算阈值。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| TM1 | 无统一上下文计量（总数/分项/水位） | 预算散落四处且只有字符数/单一 token 数 | dsh token-meter：pressure + breakdown | **P2** |

## 2. 设计（批次 A：TM1）

- `backend/chat/token_meter.py`：
  - `ContextPressure` dataclass（total/by_role/budget/pressure）+ `to_dict()`；
  - `measure_request_messages(messages, effective_window=None) -> ContextPressure`：
    纯函数；`budget = history_token_budget(effective_window)`（与截断
    同源口径）；`pressure = min(1.0, total / budget)`，budget ≤ 0 时
    pressure 恒 1.0（防御）；
  - 估算复用 `compaction.estimate_messages_tokens`（零新口径）。
- producer 埋点：请求消息装配后（legacy_routes 装配点）`logger.info`
  一行结构化 breakdown（request_id / total / by_role / budget /
  pressure / omitted）。

## 3. 批次 A 实施与验证记录

- **模块**：`backend/chat/token_meter.py`——`ContextPressure`
  dataclass（total/by_role/budget/pressure/estimator）+
  `measure_request_messages(messages, effective_window)` 纯函数；
  budget 走 `history_token_budget`（与截断/压缩同源口径），估算复用
  `estimate_messages_tokens`——零新口径、零阈值行为变更。
- **埋点**：producer 装配请求后（SE2 双路径汇合点之后）`logger.info`
  结构化 `context_pressure` 一行；try/except 降级为 debug（计量失败
  绝不阻断聊天）。
- **测试**：+8 例（基本形态 / by_role 求和 / 内容伸缩 / 封顶 1.0 /
  零预算 fail-safe / 空消息 / to_dict 形状 / env 覆盖预算同源）。
  测试窗口必须 > 16384 保留额（低于则 budget=0 走 fail-safe 分支，
  首跑踩坑已修正）。
- **验证**：新测 8 例 + history_context/compaction 回归 17 例全绿；
  ruff 全过；py38 护栏（compat_rewrite --check 0 变更 + AST 3.8）
  通过；棘轮 baseline 同步（legacy_routes.py 5514）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
- **历史轮次回填（随本轮合入总账）**：
  - R1：main #1421（`1faaa49e`）/ win7 #1425（`8194fc78`）
  - R2：main #1435（`e45dc7be`）/ win7 #1445（`aea6cad4`）
  - R3：main #1451（`67685820`）/ win7 #1459（SHA merge 后回填）
