# TDD 与 Subagent-Driven Development 工作流设计

> 状态：draft
> 日期：2026-11-11
> 范围：`backend/orchestration`、`backend/tools`、前端编排 UI

## 1. 背景与目标

sage 已有完整的编排骨架：`planner.py`（任务 DAG 分解）、`subagent_runner.py`（子 agent 执行）、`review.py`（聚合层 assertion review）、`acceptance.py`（lane 成功后跑 pytest/tsc）。

对标 Claude Code 的 Subagent-Driven Development 和 TDD 模式后，识别出三个关键缺口：

| 缺口 | sage 现状 | Claude Code 做法 |
|------|---------|----------------|
| TDD 强制工作流 | coding specialist persona 仅"建议"写测试 | 铁律：先写测试 → 看失败 → 最小实现 → 重构 |
| 任务级 review 闭环 | review 只在**聚合结果**上跑 | 每个 implementer 完成后立即跑 spec compliance + quality review |
| Acceptance 硬门控 | 建议性（checks 失败不翻转 lane 结论） | 测试不过 → 修复循环（最多 5 轮） |

**目标**：在不破坏现有骨架的前提下，补齐这三个机制，且提供可选的"快速模式"允许用户跳过 TDD。

## 2. 设计选择：工作流模式开关

用户可在三个层级选择模式：

| 层级 | 字段/入口 | 默认 |
|------|---------|------|
| 任务级 | `TaskPacket.workflow_mode: str` | `"tdd"` |
| planner | 意图识别（"跳过测试/快速实现/先出原型" → fast） | — |
| 全局 | 环境变量 `SAGE_TDD_MODE` | — |

**`tdd` 模式**：nudge 开启 + acceptance 硬门 + task reviewer 查 TDD 合规
**`fast` 模式**：nudge 关闭 + acceptance 记录但不阻塞 + reviewer 只查 spec compliance 不查 TDD

优先级：用户显式指令 > 任务元数据 > 环境变量 > 默认值。

## 3. 总体架构：统一 gate 循环

把三个机制串成一条流水线，而不是三个独立补丁：

```
┌─ TDD loop (每 lane, max_rounds=3) ────────────────────┐
│                                                       │
│  ① implementer subagent 执行                          │
│         ↓ (工具调用被 TddGuard 记录)                  │
│  ② acceptance checks  ← 硬门 (mode=tdd)              │
│         ↓ 失败                                        │
│  ③ task reviewer  ← spec compliance + TDD compliance │
│         ↓ fail                                       │
│  ④ 注入 retry_hint → 回到 ① (下一轮)                 │
│                                                       │
│  ②③ 均通过 → lane SUCCEEDED                           │
└───────────────────────────────────────────────────────┘
```

**关键复用**：`subagent_runner.py` 已有 `retry_hint` 机制（`task.parameters["retry_hint"]` 携带上次错误），`run_lane_with_retry` 已有重试框架。**不新建重试系统**。

## 4. TDD 门控与审计（B' 轻量工具级门控）

### 4.1 挂载点：BaseTool 统一钩子

`ToolRegistry` → `register_all_tools(registry, policy=policy)` 已把 policy 传给所有工具。

| 文件 | 改动 |
|------|------|
| `domain/tool_policy.py` | `ToolPolicy` (frozen) 加 `tdd_guard: Optional[TddGuard] = None` |
| `tools/base.py` | `BaseTool._observe_call(kind, payload)` — 默认 no-op，从 `self._policy.tdd_guard` 取 guard |
| `tools/file_tool.py` | WriteFileTool 上报 `("write", {"path": ...})` |
| `tools/edit_tool.py` / `patch_tool.py` | 同上 |
| `tools/bash_tool.py` | BashTool 上报 `("bash", {"command", "exit_code"})`；BashOutputTool 上报 `("bash_output", {"shell_id", "exit_code"})` |

**为什么不用 agent 调度层**：`agent.py` 有 4 处 `tool.execute()` 调用点（1629/2545/2955/3642），挂那里会漏。**为什么不用 registry 包装**：要猜参数名（`path`? `file_path`?），签名漂移就误判。工具内部上报参数名是确定的。

**注意**：`ToolPolicy` 是 frozen dataclass，但 `TddGuard` 自身可变 —— frozen 只冻结引用，符合现有 `workspace_root` 的模式。

### 4.2 识别规则

**测试文件** `is_test_path(path)`：

| 语言 | 匹配模式 |
|------|---------|
| Python | `test_*.py` / `*_test.py` / `tests/**` / `conftest.py` |
| TS/JS | `*.test.ts(x)` / `*.spec.ts(x)` / `__tests__/**` |
| Go | `*_test.go` |
| Java | `*Test.java` |
| Ruby | `*_spec.rb` |
| Rust | `tests/**` |

**测试命令** `is_test_command(cmd)`：先按 `&& ; |` 拆段再匹配

- `pytest` / `python -m pytest` / `unittest` / `vitest` / `jest` / `mocha`
- `npm test` / `npm run test` / `npm run test:*` / `pnpm test` / `yarn test`
- `go test` / `cargo test` / `mvn test` / `gradle test` / `rspec` / `phpunit` / `dotnet test`
- ⚠️ `npm run lint` / `tsc` 不算

### 4.3 nudge 规则（仅 mode=tdd，**不阻断**）

| # | 触发条件 | nudge 文本 |
|---|---------|-----------|
| 1 | 写实现文件时 `test_files` 为空 | "TDD 模式：本 lane 尚未创建测试文件。建议先写测试并运行，观察失败（red）后再实现。" |
| 2 | 写实现文件时 `test_files` 非空但从未跑过测试 | "TDD 模式：已创建测试但尚未运行。建议先运行测试观察失败（red）。" |

**每个违规类型只 nudge 一次**（防 token 浪费），全部记入 `violations` 供 reviewer 检查。

### 4.4 TDD 证据提取

```python
red_seen   = 存在 test_run 且 exit_code is not None 且 != 0
green_seen = 最后一次 impl 写入之后，存在 exit_code == 0 的 test_run
compliant  = test_files 非空 AND red_seen AND green_seen AND 无 impl_before_test 违规
```

**复用现有 `tools/test_output_parser.py`** —— 它已把 pytest/vitest/jest 的失败行解析成结构化 `test_failures`，直接作为 red 证据的补充（exit_code≠0 但解析不到失败行 = 编译错误，同样是有效 red）。

## 5. 任务级 review 闭环

**不新建 reviewer agent profile**——复用 `review.py` 的 assertion 机制（`FACT/HYPOTHESIS/NEGATIVE_EVIDENCE` + `verdict`），只换输入源。

### 5.1 新模块 `task_review.py`

构造 **task-level review prompt**（不是 aggregate-level）：

- task goal（`TaskPacket.objective`）
- implementer 输出（lane 最终 result 摘要）
- TDD 证据（`TddGuard.snapshot()`）
- acceptance 结果（`acceptance.py` report）

调用 reviewer subagent（复用 `subagent_runner` 的 lane 执行路径）。

### 5.2 三个审查维度

reviewer prompt 里显式要求：

1. **Spec compliance** — 实现是否覆盖 goal 里所有要求
2. **TDD compliance**（仅 mode=tdd）— 是否有 red→green 证据、无违规
3. **Quality** — 代码质量（复用现有 assertion 机制）

### 5.3 TDD 循环（独立于 RecoveryPolicy）

```python
class TddLoopState:
    round: int = 0
    max_rounds: int = 3  # 默认值，可配
    last_failure: Optional[str] = None
```

**为什么独立于 RecoveryPolicy**：RecoveryPolicy 的 `max_retries=2` 是 lane-level 失败重试（agent 崩溃/工具超时等）。TDD 修复是**主动改进**，需要更多轮次（Claude Code 5 轮，默认 3 轮）。混在一起会让失败重试被 TDD 修复消耗掉。

## 6. Acceptance 硬门

`acceptance.py` 增加 `gate: bool` 参数：

- `gate=True`（mode=tdd 时）：checks 失败 → lane 不标 SUCCEEDED，进入 TDD 循环下一轮
- `gate=False`（mode=fast 时）：行为与现在一致（best-effort，不阻塞）

`executor.py` 修改：`acceptance_enabled=True` 恒成立，但 `gate` 由 `workflow_mode` 决定。

## 7. 前端展示

**`LaneDetailDrawer.tsx`** 已有 acceptance 区，新增 **TDD 证据区**：

- **证据链**：红/绿状态徽章（red_seen / green_seen）+ 测试命令列表 + 退出码
- **违规列表**：impl_before_test 等违规的时间线
- **reviewer verdict**：pass/fail + assertion 列表

**新事件类型**：`lane.tdd.evidence`（在 TDD 循环每轮结束发一次）

## 8. 风险与回退

| 风险 | 缓解 |
|------|------|
| TDD 模式拖慢执行 | 每 lane 最多 3 轮 TDD 循环，上限可控 |
| is_test_path / is_test_command 误判 | 保守正则 + 不识别默认不算测试（零开销路径） |
| nudge 浪费 token | 每个违规类型只 nudge 一次 |
| 误报 reviewer 失败 | 失败原因注入 retry_hint，可审计 |
| 上线冲击 | 默认 TDD 模式，环境变量 `SAGE_TDD_MODE=fast` 全局覆盖（保守开关） |

## 9. 分阶段落地

| M | 范围 | 验证 |
|---|------|------|
| **M1** | `TddGuard` + 工具层 nudge | 单 lane 跑一个 coding 任务，检查 nudge 注入 + 事件记录 |
| **M2** | `task_review.py` + 任务级 review | 触发 review，检查 assertion 输出 |
| **M3** | TDD 循环 + Acceptance 硬门 | 故意让实现不过测试，检查修复循环 |
| **M4** | planner 意图识别 + 前端 TDD 展示 | 自然语言触发 fast 模式；UI 显示证据 |
| **M5** | 跳过路径 + 环境变量 + 文档 | 三种跳过方式都生效 |

## 10. 落地清单

**后端新增**（3 个模块）：

- `backend/orchestration/workflow_mode.py`
- `backend/orchestration/tdd_guard.py`
- `backend/orchestration/task_review.py`

**后端修改**：

- `domain/tool_policy.py` — `tdd_guard` 字段
- `tools/base.py` — `_observe_call` 钩子
- `tools/file_tool.py` / `edit_tool.py` / `patch_tool.py` / `bash_tool.py` — 各加 1-3 行上报
- `orchestration/models.py` — `TaskPacket.workflow_mode`
- `orchestration/subagent_runner.py` — 构造 TddGuard 注入 policy
- `orchestration/executor.py` — TDD 循环主逻辑
- `orchestration/acceptance.py` — `gate` 参数
- `orchestration/planner.py` — 模式识别

**前端**：

- `src/widgets/orchestration/LaneDetailDrawer.tsx` — TDD 证据展示
- 编排启动对话框 — 工作流模式下拉

**测试**（4 个新增）：

- `test_tdd_guard.py` — 识别规则 + nudge + 证据提取
- `test_workflow_mode.py` — 解析逻辑
- `test_task_review.py` — prompt 构造 + verdict 解析
- `test_tdd_gate_loop.py` — 集成：acceptance 失败触发 TDD 循环

**文档**：

- `docs/technical/` — 新章节 "TDD 工作流"（归档到技术手册）

## 11. 与现有模式的关系

| 现有机制 | 本设计的态度 |
|---------|------------|
| `RecoveryPolicy` | 保留，TDD 循环用尽后由它接手 escalate |
| `review.py` 聚合 review | 保留（final 整体验证）；本设计新增 task-level review 是补充 |
| `acceptance.py` 建议性 | mode=fast 保留原行为；mode=tdd 升级为硬门 |
| `coding` specialist persona | 保留；TDD 强制通过工具层实现，不依赖 prompt 自律 |
| `test_output_parser.py` | 完全复用，作为 red 证据的结构化解析 |
