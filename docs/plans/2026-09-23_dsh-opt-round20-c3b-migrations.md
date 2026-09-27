# DSH 对标优化·第二十轮：C3b 收编 ALTER 防御块进迁移框架

- **状态**：批次 A 交付中（分支 `feat-dshopt-r20-c3b-migrations`，基线 origin/main 含 R19）
- **系列定位**：`dsh-opt` 对标系列第 20 轮。
- **对标对象**：DeepSeek Harness 迁移纪律。

## 0. 结论速览

R9 落地了迁移框架但 MIGRATIONS 注册表为空。本轮：
- v1_schema_baseline (no-op) 注册在 runner.py 模块级
- register_migration 函数移至调用之前（修复前向引用）
- __init__.py 简化（避免循环导入 + 测试隔离冲突）
- init_db 通过 run_pending_migrations 自动应用 v1 基线

## 变更

- runner.py：register_migration 函数移至 _v1_schema_baseline 注册之前
- __init__.py 简化为 docstring（避免循环导入 + 测试隔离冲突）
- v1_baseline.py 独立文件移除（内联到 runner.py）
- init_db 调用简化（不再显式 import v1_baseline）

## 验证

- test_schema_migrations 7 例全绿
- session_repo / memory_routes 回归全绿
- py38 AST 3.8 通过；baseline 同步（legacy_routes 3976）

## 后续

- C3b v2+：将散落 ALTER 防御块逐批收编为版本迁移
- 总账 R20 行随 PR 合入自动更新
