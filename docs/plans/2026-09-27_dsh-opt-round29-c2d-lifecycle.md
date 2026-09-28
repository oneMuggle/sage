# DSH 对标优化·第二十九轮：C2d——会话生命周期装配迁出 chat_session_lifecycle

- **状态**：批次 A 交付中（分支 `feat-dshopt-r29-c2d-lifecycle`，基线 origin/main 含 R28）

## 0. 结论速览

压缩/分叉路径的装配层五函数（`_build_compaction_llm_callable` /
`_persist_compaction` / `_maybe_auto_compact_session` /
`_auto_checkpoint_if_enabled` / `_extract_legacy_chat_memory`，约 314
行）+ 日志脱敏小工具 `_safe_log_field`（唯一实现，9 行）迁出至
`backend/api/chat_session_lifecycle.py`。

legacy_routes 再导出全部六个名字：

- `legacy_session_routes` 经 `_legacy_routes._persist_compaction` 等
  **模块属性访问**的既有路径不变；
- 三处测试 patch 目标随实现更新
  （`backend.api.chat_session_lifecycle._build_compaction_llm_callable`
  ——monkeypatch 语义：patch 必须落在调用方解析名字的命名空间）；
- `_compact_in_progress` 重入护栏留 legacy_routes（路由层运行态）。

legacy_routes 3270 → 2956 行。

## 验证

- test_chat_auto_compaction 3 例 + lifecycle 相关集成 38 例全绿
- ruff 通过；py38 AST 3.8 兼容；baseline 无需更新（缩行）
