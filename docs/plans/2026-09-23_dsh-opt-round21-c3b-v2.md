# DSH 对标优化·第二十一轮：C3b v2——messages 表散落 ALTER 防御块收编

- **状态**：批次 A 交付中（分支 `feat-dshopt-r21-c3b-v2`，基线 origin/main 含 R20）
- **系列定位**：`dsh-opt` 对标系列第 21 轮。

## 0. 结论速览

将 init_db 中 messages 表的 4 个 ALTER 防御块（reasoning_content /
step_index / segment_id / subtype）收编为 v2 迁移函数注册进 MIGRATIONS。
幂等：PRAGMA 检查列存在性，已存在则跳过。

## 变更

- runner.py：新增 `_v2_messages_columns` 迁移函数 + `register_migration(2, "messages_columns", ...)`

## 验证

- test_schema_migrations 7 例全绿
- session_repo / token_meter / memory_routes 回归全绿
- py38 AST 3.8 通过；baseline 同步
