# 动态迭代预算与进度审计（2026-10-31）

> 分支：`feat/dynamic-iteration-budget`  
> Worktree：`.worktrees/feat-dynamic-iteration-budget`  
> 基线：`origin/main` @ `93f5d5b5b`

## 1. 背景与目标

当前 `run_loop` 使用固定 `max_iterations`（全局默认 25、profile 10–25），达到上限直接发出
`max_iterations_exceeded`。这导致：

- 简单任务与复杂长任务共用同一上限：简单任务可能因重复调用白耗预算，复杂任务容易被误杀；
- 用户只能手动调大上限，且默认值 25 对长任务偏低；
- 现有重复守卫（同签名 soft=3/hard=5）只能拦截"完全相同"的重复，抓不到 A,B,A,B 循环和
  "连续多步无进展"。

目标：**初始预算按任务复杂度自适应；到检查点自动判断"卡死还是确实需要"，需要则自动延长，
卡死则带证据停止，所有自动延长受资源安全预算约束。**

## 2. 方案摘要

### 2.1 两层预算

1. **安全预算（硬）**：token、墙钟、工具调用数（已有 `runTokenBudget` /
   `runWallClockLimitMinutes` / `maxToolCallsPerRun`）——真正防失控。
2. **迭代预算（软/动态）**：初始值按任务分级；到检查点由进度审计决定延长或停止。

### 2.2 初始预算

零额外 LLM 调用的启发式评分（消息长度、附件、项目绑定、关键词、计划模式、长任务模式），
映射为：

| 等级 | 初始预算 |
|------|----------|
| simple | 20 |
| medium | 80 |
| complex | 200 |
| long（用户显式长任务模式） | 400 |

Profile 的 `max_iterations` 作为下限参与取最大值，避免把用户已配置的预算降回去。

### 2.3 检查点与审计

- 检查点：达到当前预算时；之后每次延长 +50%（最少 +30、最多 +200）。
- 最多自动延长 3 次；仍需要则停止并提示用户手动继续（后续可做交互式询问）。
- 审计窗口：最近 8 个 step，记录工具签名、结果哈希、内容字符数、文件变更、产物、错误哈希。

**卡死信号：**

- 同签名重复 ≥ soft(3) / hard(5)；
- 周期调用（A,B,A,B 或 A,B,C,A,B,C 重复 ≥ 2 次）；
- 同一错误连续 ≥ 3 次；
- 连续 ≥ 6 步无新产物/文件变更/新结果哈希/内容产出。

**进展信号：** 新文件/产物、todo 写入、新工具结果哈希、内容产出。

**决策：**

- `stuck_score ≥ 0.7` → 停止（`reason=stuck`）；
- 自动延长次数耗尽 → 停止（`reason=extension_limit`）；
- 无任何进展 → 停止（`reason=no_progress`）；
- 否则 → 自动延长（受 hard cap 1000 约束）。

### 2.4 兼容与优先级

- **显式 `max_iterations` 参数**：保持硬上限，不自动延长（subagent / lane / 测试依赖此语义）。
- **`OrchSettings.max_iterations`**：
  - `0` → 保持"按各 agent profile 分别设置"，不启用动态预算；
  - `25`（默认值）→ 启用动态预算；
  - 其他正值 → 视为用户显式设置，作为硬上限，不自动延长。
- `SAGE_DYNAMIC_ITERATION_BUDGET=0` 可全局关闭动态预算（测试与排障）。

## 3. 实施步骤

- [x] 新增 `backend/core/legacy/iteration_budget.py`
  - `BudgetConfig.from_env()`
  - `estimate_initial_budget(...)`
  - `StepRecord` / `build_step_record(...)`
  - `audit_window(...)`（重复、周期、错误、无进展）
  - `decide_budget(...)`
- [x] `AgentState` 新增 `ITERATION_CHECKPOINT`；`AgentEvent` 新增 `budget_info` 字段与序列化。
- [x] `run_loop` 接入：
  - 顶部分级预算与动态开关；
  - 每轮 step 记录（从新增 messages 推导，避免改所有工具分支）；
  - 检查点审计、自动延长、停止原因；
  - `max_iterations_exceeded` 错误串追加 `reason` / `extensions`。
- [x] 前端事件契约：
  - `AgentState` 联合类型（`llmStream.ts` / `chatAndEventTypes.ts`）；
  - `agentStateMapping.ts` 两个 switch 补齐；
  - `useChat.ts` 收到 checkpoint 时 `toast.info` 提示（不打断流）。
- [x] 单测：
  - 纯函数：分级、重复、周期、无进展、决策矩阵；
  - `run_loop`：动态关闭保持旧行为；动态延长后完成；卡死停止；显式上限不延长。
- [x] 文档：本文件勾选完成项；发布/设置页 UI 留待后续 PR。

## 4. 不做（本 PR 范围）

- 交互式"继续 / 自动继续 / 停止"卡片（P1）；
- 设置页参数暴露（P1，先用 env + 代码默认）；
- lane / subagent 的独立审计接入（P1，复用同一模块）；
- 长任务模式 UI 开关（P1）。

## 5. 风险

- step 记录从消息增量推导，错误识别依赖内容前缀（`[错误]` / `[拦截]` 等），属于启发式；
- 动态延长会改变默认运行行为，必须保留 `SAGE_DYNAMIC_ITERATION_BUDGET=0` 逃生口；
- 前端新增 state 必须补全两个穷举 switch，否则 TS 编译失败（这是预期保护）。

## 6. 验收

- 既有 `test_agent_run_loop.py` / `test_agent_loop_guards.py` 全绿；
- 新增纯函数单测全绿；
- `dummy` 场景：简单完成不延长、长任务自动延长、重复调用停止；
- `ruff check` / 前端 `tsc` 通过（改动文件范围）。

## 7. 实现备注与验证结果

### 7.1 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `SAGE_DYNAMIC_ITERATION_BUDGET` | `1` | `0/false/off/no` 关闭动态预算，恢复固定上限 |
| `SAGE_DYNAMIC_BUDGET_SIMPLE/MEDIUM/COMPLEX/LONG` | 20/80/200/400 | 各档初始预算 |
| `SAGE_DYNAMIC_BUDGET_HARD_CAP` | 1000 | 自动延长硬顶 |
| `SAGE_DYNAMIC_BUDGET_EXTENSION_RATIO` | 0.5 | 每次延长比例 |
| `SAGE_DYNAMIC_BUDGET_MIN/MAX_EXTENSION` | 30/200 | 单次延长步数上下限 |
| `SAGE_DYNAMIC_BUDGET_MAX_EXTENSIONS` | 3 | 自动延长次数上限 |
| `SAGE_DYNAMIC_BUDGET_WINDOW` | 8 | 审计窗口 |
| `SAGE_DYNAMIC_BUDGET_NO_PROGRESS` | 6 | 连续无进展步数阈值 |
| `SAGE_DYNAMIC_BUDGET_ERROR_STREAK` | 3 | 连续同错阈值 |
| `SAGE_TOOL_REPEAT_SOFT/HARD_LIMIT` | 3/5 | 与既有复读守卫共用 |

### 7.2 优先级兼容

- 显式 `max_iterations` → 硬上限，不延长；
- `OrchSettings.max_iterations` = 0 → 按 profile（不延长）；
- = 25（默认）→ 动态预算；
- 其他正值 → 用户显式设置的硬上限；
- profile 值作为动态初始预算的下限。

### 7.3 验证结果（2026-10-31）

- `pytest`：`test_iteration_budget.py` + `test_agent_run_loop.py` +
  `test_agent_loop_guards.py` + `test_agent_state_transitions.py` — **86 passed**；
- `ruff check`：改动后端文件 **All checks passed**；
- 前端：`npm run typecheck` 通过；`eslint` 改动文件无输出；
- Vitest：`agentStateMapping` / `useChat.taskBoardEvents` / `chatAndEventTypes` — **48 passed**。

### 7.4 后续（P1）

- 设置页暴露上述参数与「长任务模式」开关；
- 交互式「继续 / 自动继续 / 停止」卡片；
- lane / subagent 复用同一审计器并在父级汇总；
- 把 `iteration_checkpoint` 纳入遥测与运行报告。
