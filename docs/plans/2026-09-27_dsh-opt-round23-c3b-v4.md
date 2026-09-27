# DSH 对标优化·第二十三轮：C3b v4——memories_episodic 表散落 ALTER 防御块收编

- **状态**：批次 A 交付中（分支 `feat-dshopt-r23-c3b-v4`，基线 origin/main 含 R22）

## 0. 结论速览

将 init_db 中 memories_episodic 表的 4 个 ALTER 防御块（scope /
project_key / invalid_at / supersedes_id）收编为 v4 迁移函数注册进
MIGRATIONS。幂等：PRAGMA 检查列存在性。

## 变更

- runner.py：新增 `_v4_memories_episodic_columns` 迁移函数 +
  `register_migration(4, ...)`

## 验证

- test_schema_migrations 全绿（init_db noop 期望 7→8 例更新为 {1,2,3,4}）
- py38 AST 3.8 兼容（typing 注解保留）；baseline 无需变更
  （runner.py 未入基线、database.py 本批次零改动）
