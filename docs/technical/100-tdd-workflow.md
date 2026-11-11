# TDD Subagent Workflow

> 章节：100 | 模块：`backend/orchestration` | 状态：M1–M5 已合并

## 概述

Sage 编排层借鉴 Claude Code 的 Subagent-Driven Development 与 TDD 实践，
将「写测试 → 跑测试失败（红）→ 写实现 → 跑测试通过（绿）」循环内化为 lane
执行器硬门控。目标：让每一个子 agent 的交付物都带有可验证的 TDD 证据，
同时保留"快速实现"逃生口。

## 架构

```
                ┌──────────────────────────┐
 planner.py     │ user text / LLM emit     │
                │ resolve_workflow_mode()  │──┐
                └──────────────────────────┘  │
                                              ▼
                ┌──────────────────────────┐  ┌──────────────────┐
 executor.py    │ _resolve_lane_workflow_  │──│ workflow_mode.py │
                │ mode() (priority chain)  │  │ FAST / TDD KW    │
                └──────────────────────────┘  │ SAGE_TDD_MODE    │
                          │                    └──────────────────┘
                          ▼
                ┌──────────────────────────┐
                │  TddLoopState (max=3)    │
                │  ┌────────────────────┐  │
                │  │ agent_runner call  │  │
                │  │ acceptance check   │  │
                │  │ _record_tdd_       │  │
                │  │   evidence()       │  │
                │  └────────────────────┘  │
                └──────────────────────────┘
                          │
                          ▼
                ┌──────────────────────────┐
 lane.tdd.      │ LaneEvent metadata:      │
 evidence       │   {mode, rounds,         │──► LaneDetailDrawer
                │    snapshot: {red_seen,  │    TDD 证据区
                │    green_seen, violations│
                │    test_commands}}       │
                └──────────────────────────┘
```

## 优先级链（workflow_mode 解析）

`_resolve_lane_workflow_mode(lane, task)` 返回 `"tdd"` 或 `"fast"`：

```
lane.metadata.workflow_mode          # 最高（lane 级覆盖）
  ↓ None
task.packet.workflow_mode            # planner 写入 TaskPacket
  ↓ None
task.parameters["workflow_mode"]     # planner 写入 parameters
  ↓ None
resolve_workflow_mode()
  → explicit                         # 上一步传入
  → user_text 关键词检测              # fast keywords 先于 tdd
  → os.environ["SAGE_TDD_MODE"]      # 全局回退
  → "tdd"                            # 默认
```

**关键词优先级**：`FAST_KEYWORDS` 先于 `TDD_KEYWORDS` 检测，避免「不要写测试」
（含 "写测试" 子串）被误识别为 TDD。

| 关键词 | 类别 |
|---|---|
| 跳过测试 / 别写测试 / 免测试 / 快速实现 / 先出原型 / skip tests / fast mode | fast |
| tdd / 测试驱动 / 先写测试 / test first | tdd |

## TddGuard（`tdd_guard.py`）

每次工具调用被 `TddGuard.observe_*()` 记录：

| 工具 | 上报事件 |
|---|---|
| WriteFileTool | `("write", {"path": ...})` |
| EditTool | `("edit", {"path": ...})` |
| PatchTool | `("patch", {"path": ...})` |
| BashTool / BashOutputTool | `("bash", {"command": ..., "exit_code": ...})` |

Guard 内部维护：
- `test_files`：被观察到的测试文件写入路径
- `test_runs`：`TestRun(command, exit_code, timestamp)`
- `impl_writes`：非测试文件的写入路径
- `violations`：`Violation(round, kind, detail)` 列表
- `_nudged`：已 nudge 的违规类型集合（每类只 nudge 一次）

**`compliant` 判定**：`red_seen and green_seen and len(test_files) > 0`

## TDD Loop（`executor.py`）

```python
while state.round < state.max_rounds:
    result = await agent_runner.run(...)
    rounds_run += 1
    acceptance = run_acceptance_checks(...)
    if acceptance.passed:
        _record_tdd_evidence(lane, guard, workflow_mode, rounds_run)
        break
    state.round += 1
    state.last_failure = acceptance.summary
else:
    # Exhaustion — fast 模式放行，tdd 模式降级（标记 accepted=False）
    _record_tdd_evidence(lane, guard, workflow_mode, rounds_run)
```

- `fast` 模式：acceptance 失败仅记 warning，lane 仍 succeeded
- `tdd` 模式：3 轮耗尽后 lane 标 failed（dispatcher 可触发 review）

## 前端展示（`LaneDetailDrawer.tsx`）

在「验收检查」区下方新增「TDD 证据」区：

- **模式徽章**：TDD（红→绿）/ 快速模式
- **Red/Green 徽章**：已见红（error 色）/ 已见绿（success 色）
- **统计**：循环轮次 + 违规次数
- **测试命令列表**：展示本轮 lane 跑过的所有 `pytest` / `vitest` 等命令

数据来源：订阅 `lane.tdd.evidence` 事件（`orchestrationClient.listLaneEvents`）。

## 文件清单

| 文件 | 用途 |
|---|---|
| `backend/orchestration/workflow_mode.py` | 模式解析统一入口 |
| `backend/orchestration/tdd_guard.py` | TddGuard 状态机 |
| `backend/orchestration/task_review.py` | 任务级 review 闭环 |
| `backend/orchestration/acceptance.py` | acceptance check 注册 |
| `backend/orchestration/events.py` | `LaneEvent.TDD_EVIDENCE` |
| `backend/orchestration/executor.py` | TDD 循环 + 证据发射 |
| `backend/orchestration/planner.py` | 意图识别 → workflow_mode |
| `backend/orchestration/subagent_runner.py` | runner 级模式解析 |
| `backend/data/orchestration_repo.py` | `workflow_mode` 字段回环 |
| `backend/domain/tool_policy.py` | `tdd_guard` 字段 |
| `backend/tools/{base,file,edit,patch,bash}_tool.py` | 上报 observe |
| `src/widgets/orchestration/LaneDetailDrawer.tsx` | TDD 证据区 |

## 测试覆盖

| 模块 | 测试文件 | 用例数 |
|---|---|---|
| workflow_mode | `tests/unit/test_workflow_mode.py` | 18 |
| TddGuard 状态机 | `tests/unit/test_tdd_guard.py` | 22 |
| 工具层上报 | `tests/unit/test_tdd_guard_tools.py` | 11 |
| Task review | `tests/unit/test_task_review.py` | 9 |
| TDD loop 集成 | `tests/integration/test_tdd_gate_loop.py` | 13 |
| LaneDetailDrawer | `src/widgets/orchestration/__tests__/LaneDetailDrawer.test.tsx` | 16 |

## 环境变量

| 变量 | 作用 |
|---|---|
| `SAGE_TDD_MODE` | 全局 workflow_mode 回退；接受 `"tdd"` / `"fast"`；非法值忽略 |

## 风险与限制

1. **关键词误判**：用户文本中出现 fast keyword 但实际想表达 TDD（如「我想跳过
   测试失败的阶段直接看绿」）→ 仍会被识别为 fast。缓解：planner 显式 emit 的
   workflow_mode 优先级最高。
2. **TddGuard 只观测工具调用**：不解析测试运行输出内容（exit_code = 0 即视为
   green）。复杂场景（部分失败、跳过标记）暂不区分。
3. **SQLite 证据事件存储**：单 lane 上限 1000 条事件，超长 lane 需分页查询。
