# max_iterations 可配置性与失控治理

## 背景与目标

Sage 当前对 ReAct 循环存在 6 层独立限制。限制本身必要（防死循环 + 成本失控，
`docs/verification/g004-agent-orchestration.md` 将"终止性"列为形式化保证），
但**数值配置与用户可控性存在错配**：

| 层 | 数值 | 位置 | 可配置 |
|---|---|---|---|
| run_loop 兜底 | 5 | `backend/core/legacy/agent.py:562` | ❌ 硬编码 |
| Profile 级 | primary 15 / researcher 8 / coder 15 / memory 5 / writer 10 | `backend/agents/profiles.py` | ⚠️ 有 API 无 UI |
| dataclass 默认 | 10 | `backend/agents/profiles.py:31` | ❌ |
| DB 列默认 | 10 | `backend/data/database.py:545` | ❌ |
| Subagent | 6 | `backend/tools/agent_tool.py:84` | ❌ 硬编码常量 |
| 编排 Lane | 8 | `backend/orchestration/orch_settings.py:30` | ✅ 设置 UI 可调 |
| 工具预算 | 25/run | `backend/domain/tool_policy.py:24` | ✅ |

已有真实事故：`docs/technical/40-code-exploration-tools.md` 记录用户分析
51.5 万行代码库时触发 `max_iterations_exceeded`。当时修复（PR #264/#265 引入
grep/glob/file_summary 提升单轮信息密度）方向正确，但**上限本身未动，
可配置性缺口未补**。

### 目标

1. 让 `max_iterations` 对用户可调（后端已就绪，缺前端入口）
2. 超限时给出可读的中文提示与可执行指引
3. 消除四处数值漂移，统一兜底值
4. Subagent 迭代预算纳入配置体系

### 非目标（YAGNI）

- 不实现"超限后自动续跑"或"返回部分结果"的降级执行路径（改动面大，
  涉及 run_loop 状态机语义，另行评估）
- 不调整 `max_tool_calls_per_run`（25 与 15 轮比例合理）
- 不改 Lane / 工具预算已有的可配置实现

## 涉及的文件与模块

### 前端

| 文件 | 改动 |
|---|---|
| `src/widgets/agents/EditAgentForm.tsx` | 新增 `max_iterations` 数字输入（1..50） |
| `src/shared/lib/errorMapping.ts` | 新增 agent 运行时错误码 → 中文映射 |
| `src/features/send-message/useChat.ts` | `handleError` 接入 agent 错误码映射 |
| `src/entities/setting/types.ts` | `OrchSettings` 增 `maxSubagentIterations` |
| `src/pages/settings/GeneralTab.tsx` | 增"子代理迭代上限"字段 |
| `src/pages/Agents.tsx` | mock 数值对齐真实默认值 |

### 后端

| 文件 | 改动 |
|---|---|
| `backend/core/legacy/agent.py:562` | 兜底 5 → 10，抽为具名常量 |
| `backend/orchestration/orch_settings.py` | 增 `max_subagent_iterations: int = 6` |
| `backend/tools/agent_tool.py:84` | 调用点改读 orch_settings，保留常量作兜底 |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/13-tool-system.md:35` | 修正漂移（写的 5，实为 profile 驱动） |
| `docs/05-agent.md:155` | 校对默认值表述 |
| `docs/technical/` | 归档本次变更章节 |

## 技术方案

### 关键事实更正（实施前已核实）

超限错误**不走** `mapLLMErrorToText`。实际路径：

```
agent.py:907  yield FAILED, error="max_iterations_exceeded"
   ↓
chatApi.ts:198  new Error("max_iterations_exceeded")   // 裸字符串
   ↓
useChat.ts:275  setError(err.message)                  // else 分支
   ↓
用户看到英文裸串 "max_iterations_exceeded"
```

`LLMErrorResponse` 是 LLM 传输层错误（auth/rate_limit/timeout），
`max_iterations_exceeded` 是 **agent 运行时语义错误**，二者不同类。
因此不污染 `STATIC_MESSAGES`，而是新增独立映射表。

### 方案 1：Agent 运行时错误码映射（独立于 LLM 错误）

在 `errorMapping.ts` 新增：

```ts
export const AGENT_RUNTIME_MESSAGES: Record<string, string> = {
  max_iterations_exceeded:
    '任务复杂度超出当前迭代上限，可在 Agent 管理页调高"最大迭代次数"后重试',
  tool_budget_exceeded: '工具调用次数超出单轮预算，请拆分任务后重试',
  subagent_loop_failed: '子代理执行未完成，请重试或简化子任务',
};

export function mapAgentErrorToText(code: string): string | null {
  return AGENT_RUNTIME_MESSAGES[code] ?? null;
}
```

`handleError` 在 else 分支前插入查表，命中则用中文，未命中保持原行为
（不改变既有错误的展示，向后兼容）。

### 方案 2：EditAgentForm 增字段

复用现有 `value()` 取值模式与 `onChange({...form, max_iterations})` 写入模式，
与 Max Tokens 字段同构。加 `min=1 max=50` 对齐后端 `legacy_routes.py:912` 校验。
提交前做 `Number.isInteger` 守卫，避免 `parseInt('')` → `NaN` 触发 422。

### 方案 3：兜底值统一

`agent.py:562` 的 `5` 抽为 `_DEFAULT_MAX_ITERATIONS = 10`，与 dataclass、
DB 列默认三处对齐。**注意**：profile 各角色的差异化数值（8/15/5/10）是
有意设计，不动。

### 方案 4：Subagent 预算配置化

`SUBAGENT_MAX_ITERATIONS = 6` 保留为模块级兜底常量，调用点改为读配置。
遵循 `orch_settings.py` 既有的"坏键只回落该键默认，绝不抛穿"防御模式。

## 实施步骤

- [ ] 步骤 1：后端 — `orch_settings` 增 `max_subagent_iterations`，含单测
- [ ] 步骤 2：后端 — `agent_tool.py` 调用点接入配置，保留常量兜底
- [ ] 步骤 3：后端 — `agent.py` 兜底 5 → 10 具名常量，校对 profiles/DB 一致性
- [ ] 步骤 4：前端 — `errorMapping.ts` 新增 agent 错误码映射 + 单测
- [ ] 步骤 5：前端 — `useChat.handleError` 接入映射，验证既有错误不回归
- [ ] 步骤 6：前端 — `EditAgentForm` 增 max_iterations 字段 + 组件测试
- [ ] 步骤 7：前端 — settings 增"子代理迭代上限"字段，types 同步
- [ ] 步骤 8：`Agents.tsx` mock 值对齐，文档漂移修正
- [ ] 步骤 9：全量验证（pytest + vitest + tsc）
- [ ] 步骤 10：code-reviewer + PR

## 测试策略

遵循 `testing.md` TDD（RED → GREEN → REFACTOR）：

| 层 | 用例 |
|---|---|
| 单元（后端） | `orch_settings` 读 `maxSubagentIterations`；坏值回落 6；缺段回落 |
| 单元（后端） | `agent.run_loop` 无 profile 时兜底为 10（原 5） |
| 单元（前端） | `mapAgentErrorToText` 命中/未命中；既有 LLM 错误不受影响 |
| 组件（前端） | EditAgentForm 渲染 max_iterations；改值触发 onChange；越界不提交 |
| 回归 | 现有 pytest + vitest + tsc 0 error 全绿 |

## 风险评估与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| 兜底 5 → 10 使异常路径成本翻倍 | 中 | 仅影响 profile 缺失的降级路径（正常流程不走）；10 与 DB 默认一致，实为修复不一致 |
| `handleError` 改动影响既有错误展示 | 中 | 查表未命中时严格保持原行为；补回归测试覆盖 LLM 错误路径 |
| Subagent 上限调高放大递归成本 | 中 | 默认值仍为 6，仅开放配置；`SUBAGENT_TIMEOUT_S` 与 answer cap 仍生效 |
| max_iterations 越界导致 422 | 低 | 前端 min/max + 提交前整数守卫，双重防御 |
| win7 分支同步 | 低 | 本次不同步；按项目规则 release/win7 独立演进，后续按需 cherry-pick |

### 依赖

- 无新增第三方依赖
- 后端 PATCH `/api/v1/agents/{id}` 与 1..50 校验**已存在**，无需改动
