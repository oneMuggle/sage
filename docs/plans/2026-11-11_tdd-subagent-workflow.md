# TDD Subagent Workflow Implementation Plan

> 状态：进行中
> 设计文档：`docs/superpowers/specs/2026-11-11-tdd-subagent-workflow-design.md`
> 分支：`feat/tdd-subagent-workflow`
> Worktree：`/home/fz/project/sage/.worktrees/feat-tdd-subagent-workflow`

## 背景

补齐 sage 编排层三个缺口：TDD 强制工作流、任务级 review 闭环、Acceptance 硬门控。
统一为一条 TDD gate 循环，复用现有 `retry_hint`、`run_lane_with_retry`、`test_output_parser.py`。

---

## M1: TddGuard + 工具层 nudge

### 目标
- 工具调用被 TddGuard 记录（test_files / test_runs / impl_writes / violations）
- nudge 文本注入 ToolResult（不阻断）
- 单元测试覆盖识别规则 + nudge 逻辑 + 证据提取

### 文件

**新增**
- `backend/orchestration/tdd_guard.py` — TddGuard 状态机 + 识别规则
- `backend/tests/unit/test_tdd_guard.py` — 单元测试

**修改**
- `backend/domain/tool_policy.py` — 加 `tdd_guard: Optional["TddGuard"] = None`
- `backend/tools/base.py` — 加 `_observe_call(kind, payload)` 方法
- `backend/tools/file_tool.py` — WriteFileTool 上报 `("write", {"path": ...})`
- `backend/tools/edit_tool.py` — EditTool 上报
- `backend/tools/patch_tool.py` — PatchTool 上报
- `backend/tools/bash_tool.py` — BashTool/BashOutputTool 上报 `("bash", {"command", "exit_code"})`

### 步骤

- [x] 1.1 写 `test_tdd_guard.py` 骨架（RED）
  - `test_is_test_path_python` — `test_foo.py` / `foo_test.py` / `tests/bar.py` / `conftest.py`
  - `test_is_test_path_ts` — `foo.test.ts` / `foo.spec.tsx` / `__tests__/bar.ts`
  - `test_is_test_command_simple` — `pytest` / `vitest` / `npm test`
  - `test_is_test_command_chain` — `npm run build && pytest` 提取 pytest
  - `test_is_test_command_negative` — `npm run lint` / `tsc` 不算
  - `test_nudge_write_before_test` — 写实现文件时 test_files 为空 → nudge
  - `test_nudge_only_once_per_type` — 同类型违规只 nudge 一次
  - `test_evidence_compliant` — red_seen + green_seen + test_files 非空 → compliant
  - `test_evidence_not_compliant_no_red` — 无 red → not compliant

- [x] 1.2 实现 `tdd_guard.py`（GREEN）
  ```python
  @dataclass
  class TddGuard:
      mode: str = "tdd"  # "tdd" | "fast"
      test_files: List[str] = field(default_factory=list)
      test_runs: List[TestRun] = field(default_factory=list)
      impl_writes: List[str] = field(default_factory=list)
      violations: List[Violation] = field(default_factory=list)
      _nudged: Set[str] = field(default_factory=set)

      def observe_write(self, path: str) -> Optional[str]:
          """返回 nudge 文本或 None"""

      def observe_test(self, command: str, exit_code: Optional[int]) -> None:
          """记录测试运行"""

      def snapshot(self) -> Dict[str, Any]:
          """返回证据快照供 reviewer 使用"""

      @property
      def compliant(self) -> bool: ...
  ```

- [x] 1.3 修改 `tool_policy.py` 加 `tdd_guard` 字段
  - `ToolPolicy` frozen dataclass 加 `tdd_guard: Optional[Any] = None`（类型注解用 Any 避免循环 import）
  - `from_config` 不处理此字段（由 subagent_runner 构造时注入）

- [x] 1.4 修改 `base.py` 加 `_observe_call`
  ```python
  def _observe_call(self, kind: str, payload: Dict[str, Any]) -> None:
      guard = getattr(self._policy, "tdd_guard", None)
      if guard is None:
          return
      if kind == "write":
          guard.observe_write(payload.get("path", ""))
      elif kind == "bash":
          guard.observe_test(payload.get("command", ""), payload.get("exit_code"))
  ```

- [x] 1.5 修改 `file_tool.py` / `edit_tool.py` / `patch_tool.py`
  - 在 `execute()` 成功返回前加 `self._observe_call("write", {"path": path})`

- [x] 1.6 修改 `bash_tool.py`
  - BashTool: `execute()` 返回前 `self._observe_call("bash", {"command": command, "exit_code": exit_code})`
  - BashOutputTool: 同上

- [x] 1.7 运行测试验证
  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_tdd_guard.py -v
  ```

---

## M2: task_review.py + 任务级 review

### 目标
- 复用 `review.py` assertion 机制构造 task-level review prompt
- reviewer subagent 输出 verdict（pass/fail）+ assertions
- 单元测试覆盖 prompt 构造 + verdict 解析

### 文件

**新增**
- `backend/orchestration/task_review.py` — task-level review prompt 构造
- `backend/tests/unit/test_task_review.py` — 单元测试

**修改**
- `backend/orchestration/executor.py` — Step 6.5 后调 task_review（M3 接入）

### 步骤

- [x] 2.1 写 `test_task_review.py`（RED）
  - `test_build_task_review_prompt_includes_goal` — prompt 包含 task goal
  - `test_build_task_review_prompt_includes_tdd_evidence` — prompt 包含 TDD 快照
  - `test_parse_review_verdict_pass` — 解析 `VERDICT: PASS`
  - `test_parse_review_verdict_fail` — 解析 `VERDICT: FAIL` + reason

- [x] 2.2 实现 `task_review.py`（GREEN）
  ```python
  def build_task_review_prompt(
      goal: str,
      implementer_output: str,
      tdd_snapshot: Dict[str, Any],
      acceptance_report: Optional[Dict[str, Any]] = None,
  ) -> str:
      """构造 task-level review prompt"""

  def parse_review_verdict(reviewer_output: str) -> Dict[str, Any]:
      """解析 reviewer 输出 → {"verdict": "pass"|"fail", "reason": str, "assertions": list}"""
  ```

- [x] 2.3 运行测试验证

---

## M3: TDD 循环 + Acceptance 硬门

### 目标
- acceptance.py 加 `gate: bool` 参数
- executor.py 实现 TDD 循环（acceptance 失败 → task_review → retry_hint → 下一轮）
- 集成测试覆盖完整循环

### 文件

**修改**
- `backend/orchestration/acceptance.py` — `run_acceptance_checks(..., gate: bool = False)`
- `backend/orchestration/executor.py` — TDD 循环主逻辑
- `backend/orchestration/models.py` — `TaskPacket.workflow_mode: str = "tdd"`
- `backend/orchestration/subagent_runner.py` — 构造 TddGuard 注入 policy

**新增**
- `backend/tests/integration/test_tdd_gate_loop.py` — 集成测试

### 步骤

- [x] 3.1 修改 `models.py` 加 `workflow_mode`
  ```python
  @dataclass
  class TaskPacket:
      ...
      workflow_mode: str = "tdd"  # "tdd" | "fast"
  ```

- [x] 3.2 修改 `acceptance.py` 加 `gate` 参数
  ```python
  def run_acceptance_checks(
      workdir: Optional[str],
      configured: Any = None,
      *,
      check_timeout_s: int = CHECK_TIMEOUT_S,
      gate: bool = False,  # NEW
  ) -> AcceptanceReport:
  ```
  - `gate=True` 时 failure 记入 metadata 供 executor 判断
  - `gate=False` 保持原行为（best-effort）

- [x] 3.3 修改 `subagent_runner.py` 构造 TddGuard
  ```python
  from backend.orchestration.tdd_guard import TddGuard

  # 在 run() 方法里，构造 policy 前
  workflow_mode = task.parameters.get("workflow_mode", "tdd")
  guard = TddGuard(mode=workflow_mode) if workflow_mode == "tdd" else None

  policy = ToolPolicy(
      workspace_root=policy_root,
      max_tool_calls_per_run=resolve_tool_call_budget(),
      tdd_guard=guard,
  )
  ```

- [x] 3.4 修改 `executor.py` 实现 TDD 循环
  ```python
  # Step 6.5 后新增 Step 6.6: TDD loop
  workflow_mode = lane.metadata.get("workflow_mode", "tdd")
  tdd_loop = TddLoopState(max_rounds=3)

  while tdd_loop.round < tdd_loop.max_rounds:
      # 跑 acceptance
      report = run_acceptance_checks(workdir, configured, gate=(workflow_mode == "tdd"))

      if report.all_passed:
          break  # 通过，退出循环

      # 跑 task review
      review_result = run_task_review(lane, report)
      if review_result["verdict"] == "pass":
          break  # reviewer 通过，退出循环

      # 注入 retry_hint，进入下一轮
      tdd_loop.round += 1
      tdd_loop.last_failure = review_result["reason"]
      task.parameters["retry_hint"] = {
          "attempt": tdd_loop.round,
          "last_error": tdd_loop.last_failure,
      }
      # 重新执行 lane（复用 run_lane_with_retry 逻辑）
  ```

- [x] 3.5 写集成测试 `test_tdd_gate_loop.py`（RED→GREEN）
  - `test_acceptance_failure_triggers_tdd_loop` — acceptance 失败 → 循环
  - `test_acceptance_pass_exits_loop` — acceptance 通过 → 不循环
  - `test_tdd_loop_max_rounds_respected` — 最多 3 轮
  - `test_fast_mode_no_gate` — fast 模式 acceptance 失败不阻塞

- [x] 3.6 运行测试验证
  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_tdd_gate_loop.py -v
  ```

---

## M4: planner 意图识别 + 前端 TDD 展示

### 目标
- planner 从用户文本识别 workflow_mode（"跳过测试/快速实现" → fast）
- 前端 LaneDetailDrawer 展示 TDD 证据

### 文件

**新增**
- `backend/orchestration/workflow_mode.py` — 模式解析
- `backend/tests/unit/test_workflow_mode.py` — 单元测试

**修改**
- `backend/orchestration/planner.py` — 意图识别
- `src/widgets/orchestration/LaneDetailDrawer.tsx` — TDD 证据展示

### 步骤

- [x] 4.1 写 `test_workflow_mode.py`（RED）
  - `test_resolve_mode_default` — 无输入 → "tdd"
  - `test_resolve_mode_env_override` — `SAGE_TDD_MODE=fast` → "fast"
  - `test_resolve_mode_user_text_fast` — "跳过测试" → "fast"
  - `test_resolve_mode_explicit_wins` — 显式 mode > env > default

- [x] 4.2 实现 `workflow_mode.py`（GREEN）
  ```python
  import os
  from typing import Optional

  FAST_KEYWORDS = ["跳过测试", "快速实现", "先出原型", "skip tests", "fast mode"]

  def resolve_workflow_mode(
      explicit: Optional[str] = None,
      user_text: Optional[str] = None,
  ) -> str:
      """优先级：explicit > user_text > env > default"""
      if explicit in ("tdd", "fast"):
          return explicit
      if user_text and any(kw in user_text.lower() for kw in FAST_KEYWORDS):
          return "fast"
      env = os.environ.get("SAGE_TDD_MODE", "").lower()
      if env in ("tdd", "fast"):
          return env
      return "tdd"
  ```

- [x] 4.3 修改 `planner.py` 意图识别
  - 在 `plan()` 方法里，从用户输入提取关键词调 `resolve_workflow_mode(user_text=...)`
  - 把 `workflow_mode` 写入 `TaskPacket.workflow_mode`

- [x] 4.4 修改 `LaneDetailDrawer.tsx` 展示 TDD 证据
  - 新增 "TDD 证据" 区（在 acceptance 区下方）
  - 展示：red_seen / green_seen 徽章 + 测试命令列表 + 违规时间线
  - 订阅 `lane.tdd.evidence` 事件

- [x] 4.5 运行测试验证
  - 后端 76 passed (workflow_mode 18 + tdd_guard 22 + tdd_guard_tools 11 + task_review 9 + integration 16)
  - 前端 16 passed (LaneDetailDrawer.test.tsx +2 新增)
  - ruff All checks passed

---

## M5: 跳过路径 + 环境变量 + 文档

### 目标
- 三种跳过方式都生效：task 元数据 / planner 识别 / 环境变量
- 技术手册归档

### 文件

**新增**
- `docs/technical/XX-tdd-workflow.md` — 技术手册章节

### 步骤

- [ ] 5.1 验证三种跳过方式
  - `TaskPacket.workflow_mode = "fast"` → nudge 关闭 + acceptance 不阻塞
  - 用户输入 "跳过测试" → planner 识别 → fast
  - `SAGE_TDD_MODE=fast` → 全局 fast

- [ ] 5.2 写技术手册 `docs/technical/XX-tdd-workflow.md`
  - 架构概述
  - 模式切换说明
  - TDD 证据链解释
  - 风险与回退

- [ ] 5.3 更新 `docs/technical/README.md` 章节目录

- [ ] 5.4 端到端验证
  - 启动桌面端，发起 coding 任务
  - 检查 TDD 模式下 nudge 注入 + 证据展示
  - 检查 fast 模式下无 nudge + acceptance 不阻塞

---

## 依赖与风险

| 依赖 | 说明 |
|------|------|
| `retry_hint` 机制 | 已存在（`subagent_runner.py` L230） |
| `test_output_parser.py` | 已存在，可直接复用 |
| `run_lane_with_retry` | 已存在，TDD 循环复用其框架 |

| 风险 | 缓解 |
|------|------|
| TDD 模式拖慢执行 | 每 lane 最多 3 轮，上限可控 |
| is_test_path 误判 | 保守正则 + 不识别默认不算测试 |
| nudge 浪费 token | 每个违规类型只 nudge 一次 |

---

## 验证清单

- [ ] M1 单测全绿：`pytest backend/tests/unit/test_tdd_guard.py -v`
- [ ] M2 单测全绿：`pytest backend/tests/unit/test_task_review.py -v`
- [ ] M3 集成测试全绿：`pytest backend/tests/integration/test_tdd_gate_loop.py -v`
- [ ] M4 端到端：planner 识别 fast 模式 + 前端展示证据
- [ ] M5 跳过路径：三种方式都生效
- [ ] 现有测试无回归：`pytest backend/tests/ -x --timeout=60`
