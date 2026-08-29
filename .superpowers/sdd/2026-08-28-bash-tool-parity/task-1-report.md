# Task 1 报告：提取共享子进程原语

## 文件

- 新增 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tools/subprocess_util.py`
  - 提供 `make_temp_output_file`、带 `offset` 的 `read_capped_output`、`kill_process_tree`、`unlink_quietly`。
- 新增 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tests/unit/test_subprocess_util.py`
  - 覆盖临时文件、完整读取、上限截断、增量读取、缺失文件、POSIX 进程组终止和静默清理。
- 修改 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tools/repl_tool.py`
  - 改为导入共享原语；保留 REPL 兼容薄包装与 `MAX_OUTPUT_BYTES`；调用点改用共享清理/终止函数。

## TDD 与验证

- RED：
  - `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py -q`
  - 结果：收集阶段失败，`ModuleNotFoundError: No module named 'backend.tools.subprocess_util'`。
- GREEN：
  - `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py -q`
  - 结果：`7 passed`（8 个既有 Pydantic deprecation warnings）。
- REPL 回归：
  - `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_repl_tool.py -q`
  - 结果：`23 passed`（8 个既有 Pydantic deprecation warnings）。
- Ruff：
  - `cd /home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/subprocess_util.py tools/repl_tool.py tests/unit/test_subprocess_util.py`
  - 结果：`All checks passed!`。
- `git diff --check`：通过。

## Commit

`bbec2a1b` — `refactor(tools): 提取子进程原语到 subprocess_util 供 bash 工具复用`

## Concerns

- 无功能性 concerns。
- 测试输出包含既有 Pydantic `class-based config` 弃用警告；本 Task 未涉及。

## Fix round 1

- 恢复原样文件：
  - `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/docs/superpowers/plans/2026-08-28-bash-tool-parity.md`
  - `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/docs/superpowers/specs/2026-08-28-bash-tool-parity-design.md`
- 修复 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tests/unit/test_subprocess_util.py`：使用合法的 child/grandchild Python，并通过 ready marker 轮询确认两者启动后才调用 `kill_process_tree`，移除固定 sleep 竞态。
- 验证命令：
  - `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py backend/tests/unit/test_repl_tool.py -q` → `30 passed`（8 个既有 Pydantic 弃用警告）。
  - `cd /home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/subprocess_util.py tools/repl_tool.py tests/unit/test_subprocess_util.py` → `All checks passed!`
  - `git diff --check` → 通过。
- Commit：`e8bf77e5` — `fix(tests): 稳定子进程树终止测试并恢复计划文档`。
- Concerns：无功能性 concerns；既有 Pydantic 弃用警告仍存在。

## Fix round 2

- 加固 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tools/subprocess_util.py`：`read_capped_output` 入口拒绝 bool/非 int/负数参数，并将 `cap` 限制为共享最大值 `MAX_OUTPUT_CAP_BYTES`（10 MiB）；POSIX 仅在 `pgid == pid` 时调用 `os.killpg`，否则退化为 `process.kill()`。
- 补充 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tests/unit/test_subprocess_util.py`：覆盖负 cap/offset、超最大 cap、bool 参数，以及非独立进程组不调用 `killpg`；保留独立进程组 grandchild 真实回收测试。
- 验证命令：
  - `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py backend/tests/unit/test_repl_tool.py -q` → `38 passed`（8 个既有 Pydantic 弃用警告）。
  - `cd /home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/subprocess_util.py tools/repl_tool.py tests/unit/test_subprocess_util.py` → `All checks passed!`。
  - `git diff --check` → 通过。
- Commit：待提交。
- Concerns：既有 Pydantic 弃用警告仍存在；无功能性 concerns。

## Fix round 3

- 加固 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tools/subprocess_util.py`：新增共享契约常量 `MAX_OUTPUT_OFFSET_BYTES = 2**63 - 1`，在文件打开/seek 前拒绝超限 offset；继续拒绝 bool/非 int/负数，并将读取阶段的 `OverflowError` 与 `OSError` 一并转为错误文本。
- 补充 `/home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend/tests/unit/test_subprocess_util.py`：覆盖 `MAX_OUTPUT_OFFSET_BYTES + 1` 与 `10**100`，保留真实 grandchild 进程组回收测试。
- TDD：先加测试运行失败（导入尚不存在的 `MAX_OUTPUT_OFFSET_BYTES`）；实现后测试通过。
- 验证命令：
  - `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_subprocess_util.py backend/tests/unit/test_repl_tool.py -q` → `40 passed`（8 个既有 Pydantic 弃用警告）。
  - `cd /home/fz/project/sage/.claude/worktrees/bash-tool-parity-impl/backend && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check tools/subprocess_util.py tests/unit/test_subprocess_util.py` → `All checks passed!`
  - `git diff --check` → 通过。
- Commit：待提交。
- Concerns：既有 Pydantic 弃用警告仍存在；无功能性 concerns。
