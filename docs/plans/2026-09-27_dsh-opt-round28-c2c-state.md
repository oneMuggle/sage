# DSH 对标优化·第二十八轮：C2c——流状态注册表 + 中断函数迁出

- **状态**：批次 A 交付中（分支 `feat-dshopt-r28-c2c-state`，基线 origin/main 含 R27）

## 0. 结论速览

`_ACTIVE_STREAMS` / `_PENDING_RUN_CANCELLATIONS` / `_RUN_CONFIRM_EVENTS`
三张纯内存注册表 + `interrupt_stream` / `interrupt_run` 两个中断函数
（合计 -68 行）迁出至 `backend/api/chat_stream_state.py`——纯内存状态
缝，零 DB、零 FastAPI 依赖，可完整单测。

legacy_routes 再导出全部五个名字：orch_routes 的
`from backend.api.legacy_routes import _RUN_CONFIRM_EVENTS` 既有路径
不变；调用方对注册表只做原地变异（赋键/pop/add/discard），跨模块共享
同一对象即语义正确。

## 验证

- 新增 test_chat_stream_state 7 例（none/missing 命中、agent 标记、
  dispatcher 取消、pending 令牌、dispatcher 注册表回退）
- test_interrupt_endpoint + test_chat_steer 回归 13 例全绿
- 再导出身份冒烟（is 同一对象）；ruff + py38 AST 兼容
