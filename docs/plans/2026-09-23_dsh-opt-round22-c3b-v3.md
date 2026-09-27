# DSH 对标优化·第二十二轮：C3b v3——sessions 表散落 ALTER 防御块收编

- **状态**：批次 A 交付中（分支 `feat-dshopt-r22-c3b-v3`，基线 origin/main 含 R21）

## 0. 结论速览

将 init_db 中 sessions 表的 5 个 ALTER 防御块（fork_root /
forked_at_message_id / run_status / last_error / last_run_at）收编为
v3 迁移函数注册进 MIGRATIONS。幂等：PRAGMA 检查列存在性。

## 变更

- runner.py：新增 `_v3_sessions_columns` 迁移函数 + `register_migration(3, ...)`

## 验证

- test_schema_migrations 7 例全绿
- session_repo 回归全绿；py38 AST 3.8 通过；baseline 同步
