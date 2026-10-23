# Agent 上限类错误透出具体上限值

> 实施于 PR #2356（release/win7 同步 PR #2345 至 main）。

## 背景

会话 `cb4215ba-08df-43ed-8b34-406b352e9171` 运行 17 步后失败，侧栏只显示
「运行失败」，用户既看不到真实原因，也不知道该把哪个设置调到多少。排查后
确认这是两个相互独立的缺陷叠加：

1. **失败原因在落库环节丢失**（`backend/api/legacy_routes.py`）
   `_consume_run_loop()` 内对 `_producer_error` 赋值时缺少 `nonlocal` 声明，
   Python 把该名字当成函数局部变量；外层 `finally` 读到的仍是 `None`，
   于是 `sessions.last_error` 被写成兜底文案「运行失败」。
2. **错误串不带上限数值**
   `agent.run_loop` 发出的 `AgentEvent.error` 只有裸错误码
   （如 `max_iterations_exceeded`），即使修好落库，用户也无从得知上限是
   10、25 还是 100。

## 错误串 wire format

后端统一用 `"<code> (limit=<数值>)"` 下发上限值。**后缀追加在末尾**而非
替换错误码，保证 `<code>` 仍是前缀，任何按前缀 / `startsWith` 判断的消费方
保持兼容。

| 错误码 | 产生位置 | 上限来源 |
|---|---|---|
| `max_iterations_exceeded` | `backend/core/legacy/agent.py` `run_loop` | `effective_max_iterations`（显式参数 > `OrchSettings` > `AgentProfile` > 默认 10） |
| `tool_budget_exceeded` | `backend/core/legacy/agent.py` `run_loop` | `_effective_max_tool_calls_per_run()`（env > `OrchSettings` > 策略默认 100） |
| `subagent_exhausted_iterations` | `backend/tools/agent_tool.py` | `_resolve_subagent_iterations()`（`OrchSettings.max_subagent_iterations`，默认 6） |

`tool_budget_exceeded` 的上限在一次 Run 开始时取**单次快照**，避免运行中
修改设置导致实际生效上限与报错数值不一致。

`sessions.last_error` 是单 TEXT 列，上限值随错误串一起存，**无需 DB migration**。

## 前端单一渲染点

`src/shared/lib/errorMapping.ts` 的 `mapAgentErrorToText` 是全仓唯一渲染点，
同时接受裸码与带装饰的完整串：

- 解析成功 → 把文案中的 `{limit}` 占位符替换成「数值 + 单位」；
- 裸码 → 移除 `{limit}` 占位符，绝不把占位符漏给用户；
- 未知错误码 → 返回 `null`，调用方回退展示原始文本。

解析器 `parseAgentErrorLimit` 的匹配正则为
`^([a-z][a-z0-9_]*)\s*\(limit=(\d+(?:\.\d+)?)\)$`；单位表
`AGENT_RUNTIME_LIMIT_UNITS` 通过 `Object.prototype.hasOwnProperty.call`
读取，避免原型链污染。

覆盖的两条展示路径：

| 路径 | 数据来源 | 渲染点 |
|---|---|---|
| 聊天内联错误条 | SSE `payload.error` 字符串 | `useChat.handleError` → `mapAgentErrorToText` |
| 侧栏失败徽标 tooltip | `sessions.last_error` | `src/widgets/session/SessionItem.tsx` → `mapAgentErrorToText` |

## 兼容性与回滚

- **破坏性变更**：错误串从 `"max_iterations_exceeded"` 变为
  `"max_iterations_exceeded (limit=25)"`。已全仓扫描，除本 PR 更新的 4 处
  后端断言外，无其他运行时点做精确相等比较；
  `chat_service` 的 `run_end.status` 是独立字段，不受影响；
  `subagent_runner` 用 `pytest.raises(match=...)`（正则 search），仍然命中。
- **不受影响**：`INTERRUPTED_RUN_ERROR`（「应用重启，运行中断」）来自
  `session_repo.recover_stale_run_statuses`，与 `_producer_error` 无关。
- **无新增依赖**。
- **回滚**：改动集中在单一 commit，可整笔 revert，无 DB migration。

## 回归测试

| 文件 | 覆盖 |
|---|---|
| `backend/tests/integration/test_legacy_routes_last_error.py` | SSE failed 事件带完整错误串 + `sessions.last_error` 落库不为「运行失败」 |
| `src/widgets/session/__tests__/SessionItem.failed-tooltip.test.tsx` | tooltip 渲染上限数值 / 未知错误码回退 |
| `src/shared/lib/errorMapping.test.ts` | `parseAgentErrorLimit` 正常/畸形/原型链用例 + `mapAgentErrorToText` 裸码与装饰串 |
