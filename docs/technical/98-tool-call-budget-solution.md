# 工具调用预算问题解决方案（已实施）

## 问题分析

### 根本原因

Sage 项目在执行多轮长时间任务时遇到工具调用 25 次的上限，原因是：

1. **默认预算限制**：`backend/domain/tool_policy.py` 原定义 `_DEFAULT_MAX_TOOL_CALLS_PER_RUN = 25`（私有），4 处使用魔法哨兵（`== 25`）判断"是否默认"，默认值一改就集体失效
2. **执行机制**：在 `backend/core/legacy/agent.py` 的主循环中，每次工具调用都会增加计数器，超过限制后归因为 `tool_budget_exceeded`
3. **设计目的**：这个限制是为了防止 agent 陷入无限循环或资源耗尽

### 已实施修复

- 默认值 `25` → `100`
- 私有常量 `_DEFAULT_MAX_TOOL_CALLS_PER_RUN` 提升为公开常量 `DEFAULT_MAX_TOOL_CALLS_PER_RUN`
- 4 处魔法哨兵统一引用该常量（`tool_policy.py` / `orch_settings.py` / `agent_tool.py` / `chat_service.py` / `agent.py`）
- 前端 UI 文案"0=不限"纠正为"0=默认值"（实际代码中 `0` 回落默认值而非"不限"）

## 0 值的真实语义（重要澄清）

| 设置位置 | 设为 0 的真实行为 |
|---|---|
| `OrchSettings.max_tool_calls_per_run`（UI） | **回落默认值 100**（不是"不限"） |
| `env SAGE_MAX_TOOL_CALLS_PER_RUN=0` | **回落默认值 100**（不是"不限"） |
| `ToolPolicy(max_tool_calls_per_run=0)`（代码侧） | **阻断全部工具调用**（不是"不限"） |

**结论**：没有任何路径把 0 解释为"不限"。前端文案曾经写错，现已修正。

## 解决方案（已落地）

### 方案 1: 用户临时调整

**操作步骤**：

1. 打开 Sage 桌面应用
2. 进入 **设置** → **编排（Orchestration）**
3. 找到 **工具调用预算** 字段
4. 将值调整到合适的次数（默认 100，可根据任务复杂度调整到 200-500）
5. 保存设置（实时生效，无需重启）

**推荐值**：
- 简单多轮任务：`100`（默认值，无需调整）
- 复杂长时间任务：`200-500`

### 方案 2: 通过环境变量调整（适合开发/测试/CI）

```bash
# 设置环境变量
export SAGE_MAX_TOOL_CALLS_PER_RUN=100

# 启动 Sage
npm run electron:dev
```

**优先级链**：env `SAGE_MAX_TOOL_CALLS_PER_RUN` > `OrchSettings.max_tool_calls_per_run`（UI） > 默认值 100。
任何一层非法值（< 1 / 非整数 / 空）自动回落下一层，永不抛错。

### 方案 3: 修改代码默认值（长期方案，已实施）

修改的文件清单（单一事实源）：

**`backend/domain/tool_policy.py`**
```python
DEFAULT_MAX_TOOL_CALLS_PER_RUN = 100   # 公开常量（原 25）
```

**`backend/orchestration/orch_settings.py`**
```python
_DEFAULT_FALLBACK_BUDGET = DEFAULT_MAX_TOOL_CALLS_PER_RUN
```

**`src/entities/setting/settingsRegistry.ts`**
```typescript
'orch.maxToolCallsPerRun': orchNumber(
  'orch.maxToolCallsPerRun',
  '工具调用预算',
  '单 run 工具调用总数上限，0 回落默认值（当前为 100）',
  100,
  0,
),
```

**`src/entities/setting/types.ts`**
```typescript
// 默认 100；0 回落默认值（当前为 100，不视为"不限"）。
maxToolCallsPerRun: number; // 100
```

## 风险评估

### 提高预算的风险

1. **资源消耗**：更高的预算意味着更多的工具调用，可能导致：
   - Token 消耗增加
   - 执行时间延长
   - 内存占用增加

2. **无限循环风险**：如果 agent 陷入死循环，更高的预算会延迟发现问题

### 缓解措施

1. **设置合理上限**：建议不超过 500
2. **监控执行状态**：通过日志和事件监控 agent 执行情况
3. **设置超时**：配合 `run_wall_clock_limit_min` 使用
4. **不要依赖"0=不限"**：代码中 0 不是"不限"，需要更高上限请显式设大值

## 相关文件

- `backend/domain/tool_policy.py` - 工具策略定义（单一事实源）
- `backend/orchestration/orch_settings.py` - 编排设置 + 优先级链解析
- `backend/core/legacy/agent.py` - Agent 主循环（委托 resolve_tool_call_budget）
- `backend/application/services/chat_service.py` - ChatService 预算守卫
- `backend/tools/agent_tool.py` - 子 agent 预算继承
- `src/entities/setting/types.ts` - 前端类型定义
- `src/entities/setting/settingsRegistry.ts` - 前端设置注册
- `src/pages/settings/OrchestrationTab.tsx` - 前端设置界面

## 测试覆盖

- `backend/tests/integration/test_chat_service_tool_budget.py` - ChatService 预算守卫（单批 3 用例）
- `backend/tests/integration/test_multi_turn_tool_budget.py` - 多轮长任务 + 魔法哨兵回归 + 0 真实语义
- `backend/tests/unit/test_resolve_tool_call_budget.py` - 优先级链单元测试
- `backend/tests/unit/test_agent_tool_budget.py` - SageAgent 预算守卫
- `backend/tests/unit/domain/test_tool_policy.py` - ToolPolicy 域类型单测
