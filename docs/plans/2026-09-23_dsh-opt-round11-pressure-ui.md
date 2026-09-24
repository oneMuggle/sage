# DSH 对标优化·第十一轮：上下文水位前端呈现（TM2）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r11-pressure-ui`，基线 origin/main 含 R10）
- **系列定位**：`dsh-opt` 对标系列第 11 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round4（TM1 计量，main #1462 / win7 #1466）、round10（D1a）
- **对标对象**：DeepSeek Harness Web UI 的 contextPressure 呈现——水位
  对用户可见（透明可控）。

## 0. 结论速览

TM1（R4）只落了后端结构化日志；本轮把 `context_pressure` 变成用户可见
的输入区水位徽章，补全 TM 闭环：

- **后端**：producer 在 TM1 计量点把
  `{"state": "context_pressure", "context_pressure": {...}}` 经
  `entry.queue.put_nowait` 推入活跃流（duck-typed dict，与
  `compact_triggered` 同构；try/except 降级 debug）；
- **前端**：`AgentStreamEvent` 联合加 `'context_pressure'`；useChat 增加
  handler（载荷校验走 transparencyPayload.ts 新增
  `isValidContextPressurePayload`），写入 zustand store 的
  `contextPressure` 字段；输入区上方渲染 `ContextPressureBadge`
  （≥0.8 红色警示 / ≥0.6 琥珀 / 其余隐藏）。
- i18n：`chat.contextPressure` 键（en/zh）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| TM2 | 上下文水位对用户不可见（仅后端日志） | TM1 只落日志 | dsh Web UI pressure 呈现 | **P2** |

## 2. 设计（批次 A：TM2）

- 后端事件为 duck-typed dict（不动 `AgentEvent`/`AgentState` —— 与
  `compact_triggered`/`todo_snapshot` 同构，前端 useChat 的 if 链对
  未知 state 天然容忍）。
- 载荷契约：`{total_tokens, budget_tokens, pressure(0-1 rounded4),
  by_role, estimator}`；校验器校验三数值 + by_role 对象。
- 徽章阈值：pressure ≥ 0.6 琥珀"上下文水位 xx%"、≥ 0.8 红；< 0.6 不渲染
  （默认安静）。

## 3. 批次 A 实施与验证记录

- **后端**：producer 在 TM1 计量点 `else` 分支推
  `{"state": "context_pressure", "session_id", "context_pressure": to_dict}`
  （`entry.queue.put_nowait`，队列满/关闭降级 debug）；ruff 全过。
- **前端**：types.ts 加 `'context_pressure'` state + `ContextPressurePayload`
  接口 + AgentEvent 字段；transparencyPayload.ts 加
  `isValidContextPressurePayload`（三数值 + by_role + estimator 校验）；
  useChat 镜像 compact_triggered 加 handler（写入 zustand
  `contextPressure` 字段，切换会话清空）；`ContextPressureBadge`
  （<0.6 不渲染 / ≥0.6 琥珀 / ≥0.8 红）挂 Chat 输入区上方。
- **测试**：useChat 2 例（合法写入 / 非法丢弃，per-test store 重置补充
  contextPressure: null）+ badge 5 例（阈值/会话隔离/空数据）。
  本地无 node——typecheck/vitest 由 CI Frontend job 全量复验。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位；前后端同文件树，win7 侧为纯 cherry-pick）
