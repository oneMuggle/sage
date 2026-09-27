# DSH 对标优化·第二十四轮：C2a——chat_stream 事件汇抽离（Capability Seam 第一刀）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r24-c2a-sink`，基线 origin/main 含 R23）

## 0. 结论速览

`legacy_routes.py:chat_stream_create`（约 2,100 行）内联定义了四个事件
推送闭包（agent 桥 / todo 快照 / 产物 / 工作区），共享同一形态：
**会话过滤 + `queue.put_nowait` + 满/关闭静默降级**。本轮把它们收敛为
`backend/api/chat_stream_sinks.py:StreamEventSink`——生命周期对称
（register/unregister 一对一），对 FastAPI 零依赖，可完整单测。

对标 dsh 的 Capability Seam：路由层只做"装配"，事件投影成为可替换、
可测试的独立组件。这是 chat_stream 生产线拆分的第一刀（纯机械抽取，
行为逐字节等价）。

## 变更

- 新增 `backend/api/chat_stream_sinks.py`：`StreamEventSink`
  - `emit_agent_bridge` / `push_todo_snapshot` / `push_artifact` /
    `push_workspace` 四路推送（原闭包等价实现）；
  - `register()` / `unregister()`：四路监听一对一注册注销
    （agent_event_bridge / todo_state / artifact_repo / workspace_events）；
  - `push_persisted_todo()`：流启动时持久化 todo 快照（原 B4 内联 await put）；
- `legacy_routes.py`：四个内联闭包 + 注册/注销块 → sink 装配
  （预计 -100 行左右）；

## 不做

- `chat_stream_create` 其余部分（producer 主循环、编排派遣、终态闭环）
  不动——留给后续轮次逐刀拆分；
- 监听器注册表（todo_state / artifact_repo / workspace_events /
  agent_event_bridge）零改动。

## 验证

- 新增 `backend/tests/unit/test_chat_stream_sinks.py`：
  会话过滤、队列满静默降级、register/unregister 对称（fake 监听注册表）；
- 既有 chat_stream 集成测试（test_chat_stream 等）回归；
- ruff + py38 AST 兼容；architecture-baseline：legacy_routes 缩行无需
  更新（棘轮只红增长），新文件未入基线且远低于全局上限。
