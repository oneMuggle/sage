# Task 3 修复轮报告：后台 shell 会话注册表

## 实际改动

- `/home/fz/project/sage/.claude/worktrees/agent-a1e33d9625fe39678/backend/tools/bash_session.py`
  - `read_increment`/`terminate` 在查表和任何状态变更前严格验证 cap：拒绝 bool、非 int、<=0 及超过 `MAX_OUTPUT_CAP_BYTES`。
  - `terminate` 不再先 pop；先杀进程、尽力 drain，`finally` 中无论 drain 是否异常都 unlink 两个路径并移除 session；drain 逻辑异常在清理后重新抛出。
  - 注册日志只保留 shell_id；容量超限时清理新进程及两个文件。
  - 注册时检查 POSIX 进程组是否独立，无法验证或不独立时记录非敏感 warning。
  - `clear` 通过可复入的 RLock 和 terminate 清理全部会话。
- `/home/fz/project/sage/.claude/worktrees/agent-a1e33d9625fe39678/backend/tools/subprocess_util.py`
  - `unlink_quietly` 保持不抛异常契约，但对失败记录 basename warning。
  - 新增 `BoundedOutputCollector` / `start_bounded_output_collectors`：后台消费 stdout/stderr PIPE，每个临时文件最多写入 `max_bytes`，超限后继续消费并标记 `overflowed`，避免磁盘无限增长及 PIPE 死锁。
  - 保留 Task 1 既有函数和签名兼容。
- `/home/fz/project/sage/.claude/worktrees/agent-a1e33d9625fe39678/backend/tests/unit/test_bash_session.py` 保留原 Task 3 行为测试（10 项）；collector 接口已提供给未来 Task 4 `_spawn` 接入。

## 测试命令与结果

- `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_bash_session.py -q`：10 passed。
- `/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/tools/bash_session.py backend/tools/subprocess_util.py`：All checks passed。
- `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m py_compile backend/tools/bash_session.py backend/tools/subprocess_util.py`：通过。
- `git diff --check`：通过。
- 目标中提到的 `backend/tests/unit/test_subprocess_util.py` 在当前工作树不存在，未执行该不存在路径。

## 共享接口

`start_bounded_output_collectors(stdout, stderr, stdout_path, stderr_path, max_bytes=MAX_OUTPUT_CAP_BYTES)` 返回 `(stdout_collector, stderr_collector)`；调用方应在启动 Popen 后保存 collector，并在终止时 `join()`，通过 `overflowed` 观察是否超限。该接口尚未改变 Task 1 调用方；Task 4 `_spawn` 需要使用 `Popen(..., stdout=PIPE, stderr=PIPE)` 接入。

## 剩余 concern

- 当前 `BashSession` 尚未保存 collector 字段，因此未来 `_spawn` 必须在会话生命周期中持有并 join collector；仅调用现有文件重定向路径不会自动获得有界 collector。
- 后端重启后内存注册表外的孤儿进程仍不会恢复清理，这是原设计限制。
- `kill_process_tree` 保持清理路径不抛异常；进程组契约 warning 只能观测风险，无法替调用方修正缺失的 `start_new_session=True`。
