# 2026-10-22 Agent「超过上限」类错误透出具体上限值

## 背景与目标

会话 `cb4215ba-08df-43ed-8b34-406b352e9171` 失败，根因是 ReAct 迭代预算耗尽
（`max_iterations_exceeded`），但侧栏与聊天错误提示都**看不到上限是多少**，
用户无法判断该调到多少。

排查同时发现一个独立缺陷：`legacy_routes.py` 的 `_consume_run_loop()` 嵌套函数
**漏写 `nonlocal _producer_error`**，导致 FAILED 分支里的赋值变成函数局部变量，
外层 `finally` 读到的仍是 `None` → `sessions.last_error` 落库退化成
`"运行失败"`，真实原因永远丢失（本例中就是 `max_iterations_exceeded`）。

**目标：**

1. 修复 `nonlocal` 缺陷，让失败原因能落库。
2. 所有「超过上限」类错误在**用户可见的提示**中带出**具体上限数值**，
   让用户知道该调到多少。

## 涉及的文件与模块

| 文件 | 改动 |
| --- | --- |
| `backend/api/legacy_routes.py` | 补 `nonlocal _producer_error`；spend/timeout 错误文案带上限 |
| `backend/core/legacy/agent.py` | `max_iterations_exceeded` / `tool_budget_exceeded` 带上限 |
| `backend/tools/agent_tool.py` | `subagent_exhausted_iterations` 带子代理迭代上限 |
| `src/shared/lib/errorMapping.ts` | 解析 `"<code> (limit=<N>)"` 并把上限插入中文文案 |
| `src/widgets/session/SessionItem.tsx` | 侧栏失败 tooltip 走 `mapAgentErrorToText`（不再显示裸码） |
| `backend/tests/unit/test_agent_*.py` | 更新被新错误串格式影响的断言（4 处） |
| `backend/tests/integration/test_legacy_routes_last_error.py` | 新增：失败原因 + 上限值落库回归测试 |
| `src/shared/lib/errorMapping.test.ts` | 补充上限解析/渲染用例 |
| `src/widgets/session/__tests__/SessionItem.failed-tooltip.test.tsx` | 新增：侧栏失败 tooltip 文案用例 |

## 技术方案

### 1. wire 格式：`<code> (limit=<数值>)`

后端所有「超过上限」类错误的 `error` 字段统一为：

```
max_iterations_exceeded (limit=25)
tool_budget_exceeded (limit=100)
```

约定：`<code>` 是稳定机器码（保持可 grep、可精确匹配），`limit=` 是可选后缀，
值为次数（整数）或金额（浮点，USD）。

选择「装饰同一个字符串」而非「新增 `error_detail` 字段」的原因：
`sessions.last_error` 是 TEXT 单列，侧栏 tooltip 直接展示该字符串——
限额信息必须能编码进这一个字符串才能覆盖侧栏与聊天两条展示链路。
后缀放最后保证 `<code>` 仍是前缀，任何 `startsWith(code)` 语义不受影响。

### 2. 前端单一渲染点

`mapAgentErrorToText` 现在接受带后缀的原始串：

- 先用正则拆出 `code` 与 `limit`；
- `code` 命中 `AGENT_RUNTIME_MESSAGES` 才返回中文，否则返回 `null`
  （保持「未知码回退原始文本」的既有行为）；
- 命中后把消息模板里的 `{limit}` 占位替换为 `（当前上限 25 次）`。

消息模板（`AGENT_RUNTIME_MESSAGES`）新增 `{limit}` 占位，无上限时占位替换为空串，
文案仍然通顺——**未知上限不会退化成空白或 `undefined`**。

`useChat.handleError` 与 `SessionItem` 两处展示点都调这一个函数，
避免中文文案在前后端各写一份导致漂移。

### 3. 覆盖的 4 类上限错误

| 错误码 | 上限来源 | 展示位置 |
| --- | --- | --- |
| `max_iterations_exceeded` | `effective_max_iterations`（4 级优先级链） | 聊天横幅 + 侧栏 tooltip |
| `tool_budget_exceeded` | `_effective_max_tool_calls_per_run()` | 聊天横幅 + 侧栏 tooltip |
| `subagent_exhausted_iterations` | `_resolve_subagent_iterations()` | 聊天横幅（子代理工具错误串） |
| `spend_limit_exceeded` | `OrchSettings.spend_limit_usd` | 后端直出中文文案（带金额） |
| `llm_total_timeout` | `llm_total_timeout_s()`（app_settings > env > 1800；0 = 不限） | wire 形式 `llm_total_timeout (limit=N)` 进 `sessions.last_error`（侧栏 tooltip，走 `mapAgentErrorToText` 渲染中文）；中文文案进流式 error envelope（聊天横幅，显式排除网络语义） |

后两类本来就以 `{type, message}` 字典形式下发（`message` 即最终文案），
所以只需在后端把上限数值写进 `message`，前端 `chatApi.ts` 会原样透出。

## 实施步骤

- [x] 步骤 1：定位失败根因 + 确认 `nonlocal` 缺陷（已在 `release/win7` 验证）
- [x] 步骤 2：设计 wire 格式与单一渲染点
- [x] 步骤 3：`legacy_routes.py` 补 `nonlocal _producer_error` + spend/timeout 文案带上限
- [x] 步骤 4：`agent.py` 两条上限错误带上限
- [x] 步骤 5：`errorMapping.ts` 支持上限解析与渲染
- [x] 步骤 6：`SessionItem.tsx` tooltip 走中文映射
- [x] 步骤 7：更新受影响的后端断言 + 补前端/后端回归测试
- [x] 步骤 8：跑后端 pytest（`sage-backend` 环境）+ 前端 vitest/tsc/eslint
- [ ] 步骤 9：代码审查（code-reviewer）
- [ ] 步骤 10：cherry-pick 同步到 `release/win7`

## 风险评估与依赖

| 风险 | 处置 |
| --- | --- |
| 错误串格式变化打断精确相等断言 | 已知 4 处（`test_agent_run_loop` ×2、`test_agent_tool_budget`、`test_agent_parallel_interrupt`），随步骤 7 一并更新为带 limit 的精确断言 |
| `mapAgentErrorToText` 精确匹配语义 | 保留 `hasOwnProperty` 防御；`code` 拆分后仍走原表，未知码返回 `null` |
| `classifyEndpointError` 误判 | 该函数要求 `error` 为对象且带 `type`，字符串一律返回 `null`，不受影响 |
| `subagent_runner` / `agent_tool` 透传 | 二者只做字符串透传，装饰后自动携带上限，无需改动 |
| 双分支漂移 | main 先实现并验证，再 cherry-pick 到 `release/win7` 并单独跑 py38 测试 |

## 依赖

无新增依赖。
