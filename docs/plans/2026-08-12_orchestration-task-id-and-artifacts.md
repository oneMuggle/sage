# 编排修复：task_id 编号碰撞 + 普通聊天 artifacts 落库 + maxItems 解耦

**日期:** 2026-08-12
**分支:** `fix/orchestration-task-id-and-artifacts`
**状态:** 已完成（待 PR）

## 背景与目标

用户实测多 agent 编排（方案 C / Chat-Native，PR #296）时发现：

1. 复杂任务（"学习量化交易…"）触发编排后，UI 任务板**始终显示"完成 3/6"**，即使 6 个子任务真实完成、3 个文件已落盘。
2. 最后回复声称生成了 `Quant_Trading_Comprehensive_Manual.md`，但用户在 UI 里找不到——文件实际写在仓库根目录，且 Artifacts 面板无任何入口。
3. `dispatch_subagents` schema `maxItems: 4` 与计划上限 8 结构性断裂，导致 6 任务计划被迫拆 3 批派发（"4 轮"现象诱因）。

根因（已代码级确认）：

- **F1（HIGH）** `ChatDispatcher` 每次 dispatch 调用都从 `t1` 重新编号
  （`chat_dispatcher.py: task_id=f"t{index+1}"`，index 是本次调用内下标），
  而计划 task_id 是全局 `t1…t6`（`legacy_routes.py:1781`）。前端 reducer
  按 task_id 合并（`useChat.ts:389`）、任务板按 plan 的 task_id 查状态
  （`TaskTreeSection.tsx:53`）→ 计划里 t4/t5/t6 **永远收不到 status 更新**，
  UI 恒显 3/6。
- **F2（HIGH）** producer 只在 `_auth_result is not None` 时
  `set_tool_context`（`legacy_routes.py:1659`）。普通聊天无 office refs +
  无 binding → `_auth_result None` → `file_tool._record_artifact_safely`
  因 `current_tool_context() is None` 静默早退（`file_tool.py:110`）
  → artifacts 表恒空 → 前端无产物入口。
- **F3（MEDIUM）** `maxItems: 4` 与 `MAX_CONCURRENT_SUBAGENTS=4` 概念耦合。
  maxItems 管"单次调用任务数"、信号量管"同时运行数"，二者正交。计划上限 8
  被派发钳到 4 → 6 任务强制 3 批，多轮 ReAct + 放大编号碰撞面。
- **F4（MEDIUM）** planner `_sanitize_tasks` 不校验 `agent_hint` 合法性，
  LLM 可产出 `content_writer`/`editor` 等**不存在的角色**
  （`profiles.py` 默认集只有 primary/researcher/coder/memory_manager/writer）。
  本次靠 conductor 自行改用 researcher/writer 才偶然跑通。

## 涉及文件

| 文件 | 改动 |
|---|---|
| `backend/orchestration/chat_dispatcher.py` | F1 全局计数器；F3 聚合总上限 |
| `backend/tools/subagent_tool.py` | F3 `maxItems: 4 → 8` |
| `backend/api/legacy_routes.py` | F2 普通聊天也 set_tool_context |
| `backend/orchestration/planner.py` | F4 agent_hint 校验到合法角色集 |
| `backend/tests/unit/test_chat_dispatcher.py` | F1/F3 新测试 |
| `backend/tests/unit/test_subagent_tool.py` | F3 schema 断言 4→8 |
| `backend/tests/unit/test_planner_llm.py` | F4 新测试（丢弃非法/禁用/保留自定义 hint） |
| `backend/tests/integration/test_chat_orchestration_stream.py` | F2 集成测试 |
| `backend/tests/integration/test_chat_office_tools.py` | F2 语义更新（无 binding 也设空 scope ctx） |

## 技术方案

### F1：ChatDispatcher 全局 task 计数器

`__init__` 加 `self._next_task_index = 0`。`dispatch()` 里每分配一个任务用
`f"t{self._next_task_index + 1}"` 后 `self._next_task_index += 1`（**含
malformed KeyError 分支**）。conductor 顺序调工具，同一 run 内三次派发 →
`t1-t6` 全局唯一，与计划编号对齐。现有单次调用测试不受影响。

### F2：普通聊天总是设置 ToolExecutionContext

producer 闭包内 `_auth_result is None` 分支构造
`ToolExecutionContext(session_id=data.session_id, stream_id=stream_id,
binding_generation=0, office_doc_scope=frozenset())`，然后无条件
`set_tool_context`。影响面：
- `_record_artifact_safely` 现在有 session_id → artifacts 落库 ✅（目标）
- `todo_state.resolve_session_id` 从匿名桶 → 真实 session_id（语义更正确）
- office 工具普通聊天不注册（primary profile 白名单无），低风险

### F3：maxItems 4→8 + 聚合总上限

- `INPUT_SCHEMA.maxItems: 4 → 8`（= `MAX_PLAN_TASKS`，注释同步更新，说明
  maxItems 与并发解耦）
- `chat_dispatcher.py` 新增 `MAX_AGGREGATE_CHARS`（120KB），`_aggregate`
  返回前对整体截断 + 尾部提示，防 8 项最坏 400KB 灌爆 conductor 上下文

### F4：planner agent_hint 校验

`_sanitize_tasks` 对 `agent_hint` 用 `_is_dispatchable_agent()` 校验（延迟
import `get_enabled_agent()`，读 SQLite 运行时状态）→ 不在合法角色集
（不存在/已禁用）→ 丢弃（不写入 `parameters.agent_hint`），conductor 用
默认角色。**为何不用 `get_agent_registry()`**：内存注册表不反映 SQLite
enabled 状态（toggle_agent 禁用后仍残留），且不含自定义 agent（只存
SQLite）；用与 `ChatDispatcher._run_subagent` 完全相同的 `get_enabled_agent`
判定，保证 planner 放行的 hint 一定能成功派发。

## 实施步骤

- [x] F1：全局计数器 + 单测（先写 RED 测试）
- [x] F3：maxItems 8 + 聚合上限 + 单测
- [x] F2：producer ctx + 集成测试
- [x] F4：planner agent_hint 校验 + 单测
- [x] 全量相关 pytest 回归（56 + 60 + 41 + 22 passed；ruff 0 error）
- [x] AI 审查（python-reviewer）+ 修复 2 HIGH（ruff SIM102、F4 语义缺口）

## 审查记录（python-reviewer, 2026-08-12）

- **HIGH 已修**：F4 初版用 `get_agent_registry()`（内存默认注册表）——
  不反映 SQLite enabled、漏自定义 agent。改 `get_enabled_agent()` 后精确
  对齐派发判定；同时合并嵌套 if 消除 ruff SIM102（CI 门控）。
- **MEDIUM 已记录**：task_id 对齐仅在 conductor 连续按序整批派发时成立；
  合并/乱序/跳过重试会错位（F3 放宽 maxItems 缓解，但未根除）。后续
  建议把计划 task_id 随工具调用传入或按 (agent_id, goal) 匹配。
- **LOW**：office `requires_tool_context` 门因 F2 失效（防御纵深弱化，profile
  白名单兜底）；F3 截断提示文案易误导 conductor（可接受取舍）。
- **LOW**：3 个仓库根 untracked `.md` 产物是真实运行中 write_file 以相对
  路径落到 cwd 的残留；「无绑定会话 write_file 落 cwd」属更上游卫生问题，
  建议后续单独治理。

## 风险与依赖

- 无 DB schema 变更；无前端改动（编号对齐后现有 reducer 自动正确）。
- F3 聚合上限是防御性兜底，不改变正常输出格式。
- 依赖：`test_subagent_tool.py:34` 现有断言 `maxItems == 4` 需随 F3 更新。
