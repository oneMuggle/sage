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
