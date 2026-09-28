# DSH 对标优化·第三十一轮：C2f——聊天流支撑函数迁出 chat_stream_support

- **状态**：批次 A 交付中（分支 `feat-dshopt-r31-c2f-chatkit`，基线 origin/main 含 R30）

## 0. 结论速览

producer 与聊天路由共用的六组支撑逻辑（约 143 行）迁出至
`backend/api/chat_stream_support.py`：orch run 终态闭环
（`_finalize_orch_run`）、dispatcher 构造（`_build_orchestration_dispatcher`）、
图片附件校验（`_validate_chat_images` + 三常量）、memory_used 事件构造
（`_memory_used_event_from_hits`）、工作段清理（`_clear_working_segment`）、
NDJSON 序列化（`_ndjson`）。

legacy_routes 再导出全部名字——**调用方（producer）留在 legacy_routes**，
`test_chat_stream` patch `backend.api.legacy_routes._finalize_orch_run`
的 seam 不受影响（与 R29 不同：那次调用方随实现迁移，patch 目标需更新）。

legacy_routes 2748 → 2619 行。

## 验证

- test_chat_images + test_chat_stream 19 例全绿；再导出身份（is）一致
- ruff 通过；py38 AST 3.8 兼容；baseline 无需更新（缩行）
