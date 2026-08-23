# Task 2 Report: SendMessage 式子代理续聊

## 实现内容

- `ChatTaskState` 新增 `parent_task_id`，`ChatDispatcher` 新增 run 内 `_histories`。
- `dispatch()` 支持可选 `followup_of`：仅接受当前 run 中已存在且 `status == "done"` 的 task；非法值记录 warning 并降级为普通任务。
- 有效 followup 自动把父任务加入依赖图，并把父任务历史注入新 Task 的 `parameters["history"]`。
- `_run_subagent()` 从 `LaneExecutor` 成功结果的 `result.messages` 保存历史，同时保留既有字符串 output 和 monkeypatch 兼容行为。
- `SubagentRunner` 增加 `MAX_REPLAY_MESSAGES = 20`，重放时保留首条 system 与最近 20 条历史消息，再追加新的 user goal；history 缺失或非法时走旧路径。
- `dispatch_subagents` schema 与描述增加 `followup_of`。

## TDD 与验证

1. 先新增 followup 路由、历史重放、schema 失败测试，确认实现前按预期失败。
2. 实现后指定测试通过：
   - `44 passed, 5 warnings`
3. 本次修改文件 ruff 通过：
   - `orchestration/chat_dispatcher.py`
   - `orchestration/subagent_runner.py`
   - `tools/subagent_tool.py`
   - 相关三个 unit test 文件
4. `git diff --check` 通过。

## 已知事项

全仓 `ruff check .` 仍被既有 `backend/tests/electron` 中 7 个 F401/F841 问题阻断，均不在本任务修改范围内。
