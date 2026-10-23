# Agent 上限类错误透出具体上限值

> 日期：2026-10-22
> 分支：`feat/agent-limit-error-details`（从 `main` 切出）
> 触发：用户反馈会话 `cb4215ba-08df-43ed-8b34-406b352e9171` 失败且错误提示无信息量

## 背景与目标

### 现象

会话 `cb4215ba-08df-43ed-8b34-406b352e9171` 在跑完 17 步 bash 探索后失败，
侧栏只显示「运行失败」，用户既看不到失败原因，也不知道该把哪个设置调到多少。

### 两个独立根因

1. **`nonlocal` 缺失**（`backend/api/legacy_routes.py`）
   `_consume_run_loop()` 内对 `_producer_error` 赋值时没有声明 `nonlocal`，
   Python 闭包把它当成函数局部变量；外层 `finally` 读到的仍是 `None`，
   于是 `sessions.last_error` 落库成兜底文案「运行失败」，
   真实原因（`max_iterations_exceeded`）在落库环节丢失。

2. **错误串不带上限值**
   `agent.run_loop` 发出的 `AgentEvent.error` 只有裸错误码
   （`"max_iterations_exceeded"`），即便修好落库，用户也不知道上限是 25 还是 100。

### 目标

- 失败会话能看到**真实原因**；
- 超过上限类错误，提示里**带出具体上限数值**，用户知道该调到多少、去哪调。

## 涉及文件与模块

| 文件 | 改动 |
|---|---|
| `backend/api/legacy_routes.py` | 补 `nonlocal _producer_error`；花费限额/超时文案带出上限数值 |
| `backend/core/legacy/agent.py` | `tool_budget_exceeded` / `max_iterations_exceeded` 追加 ` (limit=N)` |
| `backend/tools/agent_tool.py` | `subagent_exhausted_iterations` 追加 ` (limit=N)` |
| `src/shared/lib/errorMapping.ts` | 新增 `parseAgentErrorLimit` / `AGENT_RUNTIME_LIMIT_UNITS`；`mapAgentErrorToText` 渲染上限值 |
| `src/widgets/session/SessionItem.tsx` | 失败徽标 tooltip 用 `mapAgentErrorToText` 渲染 `last_error` |
| `backend/tests/integration/test_legacy_routes_last_error.py` | 新增：失败原因落库回归测试 |
| `src/widgets/session/__tests__/SessionItem.failed-tooltip.test.tsx` | 新增：tooltip 渲染回归测试 |
| `src/shared/lib/errorMapping.test.ts` | 新增：`parseAgentErrorLimit` + 上限渲染用例 |

## 技术方案

### 错误串 wire format

后端统一用 `"<code> (limit=<数值>)"` 下发上限值，**后缀追加在末尾**而非替换错误码，
保证 `<code>` 仍是前缀，任何按前缀 / `startsWith` 判断的消费方都保持兼容。

| 错误码 | 来源 | 上限来源 |
|---|---|---|
| `max_iterations_exceeded` | `agent.run_loop` | `effective_max_iterations`（显式参数 > OrchSettings > AgentProfile > 默认 10） |
| `tool_budget_exceeded` | `agent.run_loop` | `_effective_max_tool_calls_per_run()`（env > OrchSettings > 策略默认 100） |
| `subagent_exhausted_iterations` | `agent_tool` | `_resolve_subagent_iterations()`（`OrchSettings.max_subagent_iterations`，默认 6） |

### 前端单一渲染点

`mapAgentErrorToText` 扩展为同时接受裸码与带装饰的完整串：

- 解析成功 → 用 `{limit}` 占位符替换成「数值 + 单位」；
- 裸码 → 移除 `{limit}` 占位符（绝不把占位符漏给用户）；
- 未知错误码 → 返回 `null`，调用方回退原始文本。

`sessions.last_error` 是单 TEXT 列，无需 DB migration —— 上限值随错误串一起存。

### 覆盖两条展示路径

| 路径 | 数据来源 | 渲染点 |
|---|---|---|
| 聊天内联错误条 | SSE `payload.error` 字符串 | `useChat.handleError` → `mapAgentErrorToText` |
| 侧栏失败徽标 tooltip | `sessions.last_error` | `SessionItem.tsx` → `mapAgentErrorToText` |

## 实施步骤

- [x] 步骤 1：定位根因（`nonlocal` 缺失 + 错误串不带上限）
- [x] 步骤 2：`agent.py` 装饰两个上限类错误串
- [x] 步骤 3：`agent_tool.py` 装饰子代理上限错误串
- [x] 步骤 4：`legacy_routes.py` 补 `nonlocal` + 花费限额/超时文案带上限
- [x] 步骤 5：`errorMapping.ts` 新增解析器 + 上限渲染
- [x] 步骤 6：`SessionItem.tsx` tooltip 走 `mapAgentErrorToText`
- [x] 步骤 7：更新 4 处既有后端测试断言
- [x] 步骤 8：新增后端集成测试 + 前端 tooltip 测试 + errorMapping 单测
- [x] 步骤 9：代码审查（code-reviewer agent）并处理发现
- [x] 步骤 10：ruff / tsc / eslint + 后端 171 测试 + 前端 67 测试全绿
- [ ] 步骤 11：cherry-pick 同步到 `release/win7`（文案差异：`Lane 迭代上限` vs `Agent 迭代次数上限`；py38 兼容检查）
- [ ] 步骤 12：并入 `docs/technical/` + `docs/user-manual/`，删除本计划文件

## 审查发现与处理

| 级别 | 发现 | 处理 |
|---|---|---|
| HIGH | 文案指向「Agent 管理页」——实际 UI 路径是 `设置 → 编排`（独立顶层 Tab） | 已改为「设置 → 编排 → Agent 迭代次数上限」等真实路径 |
| MEDIUM | `parseAgentErrorLimit` 正则 `^([a-z_]+)` 允许畸形码 | 收紧为 `^([a-z][a-z0-9_]*)` |
| MEDIUM | `AGENT_RUNTIME_LIMIT_UNITS` 裸索引有原型链风险 | 改用 `Object.prototype.hasOwnProperty.call` |
| MEDIUM | 后端超时路径无回归测试 | 记为后续项（该路径不依赖 `nonlocal`，风险低） |
| LOW | `AgentErrorLimit.value` 无生产消费者 | 保留（程序判断用），文本渲染走 `text` 保精度 |
| LOW | `limit=0` 文案歧义 | 记为后续项（0 = 禁用工具调用的极端配置） |

## 风险评估与依赖

- **破坏性变更**：错误串从 `"max_iterations_exceeded"` 变为 `"max_iterations_exceeded (limit=25)"`。
  已全仓扫描：除本 PR 更新的 4 处后端断言外，无其他运行时点做**精确相等**比较。
  `chat_service` 的 `run_end.status` 是独立字段，不受影响；
  `subagent_runner` 用 `pytest.raises(match=...)`（正则 search），仍然命中。
- **跨模块**：`INTERRUPTED_RUN_ERROR`（`应用重启，运行中断`）来自
  `session_repo.recover_stale_run_states`，与 `_producer_error` 无关，未受影响。
- **依赖**：无新增依赖。
- **回滚**：全部改动可 revert 单一 commit，无 DB migration。
