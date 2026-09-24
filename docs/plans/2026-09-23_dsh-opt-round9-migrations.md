# DSH 对标优化·第九轮：schema 版本化迁移框架（C3 第一刀）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r9-migrations`，基线 origin/main 含 R8）
- **系列定位**：`dsh-opt` 对标系列第 9 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round1-8；R8 交付：main #1499（`9b8bbd44`）/ win7 #1505（`cb136fb1`）
- **对标对象**：DeepSeek Harness 的会话格式"代"纪律——**迁移只新增版本
  命名的后继，绝不移动 / 覆写 / 删除已提交代**；迁移是存储内部细节。

## 0. 结论速览

`database.py` 的 schema 演进全靠 `CREATE TABLE IF NOT EXISTS` + 散落的
`ALTER` 防御块，无版本号——无法回答"这个库跑的哪一版 schema"，也无法
表达需要**数据改写**的迁移。本轮落版本化迁移框架（C3 地基）：

- `schema_version` 账本表（version/name/applied_at）；
- `MIGRATIONS` 有序注册表（只追加，版本号严格递增，框架拒绝倒序注册）；
- `run_pending_migrations(conn)`：幂等应用未执行迁移；失败上抛不留账本
  记录（半应用可定位）；init_db 末尾接线（fail-fast——迁移失败比带病
  启动安全，与"绝不覆写已提交代"配套）。
- 既有幂等 DDL 保持原位（等价于基线 schema）；注册表生产侧为空，本轮
  纯地基，零行为变更。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| C3a | schema 无版本号、无迁移框架 | database.py 防御块演进，无法表达数据改写 | dsh 格式代纪律 | **P2** |

## 2. 设计（批次 A：C3a）

- `backend/data/migrations/runner.py`：`ensure_version_table` /
  `applied_versions` / `register_migration`（版本号必须严格递增）/ 
  `run_pending_migrations`（按序应用、已应用跳过、失败上抛）。
- 迁移函数约定：`(conn) -> None`，自行 commit；合入后版本号与函数体
  **只修 bug 不改语义**。
- init_db 接线：`conn.commit()` 之后调用（此时全部既有 DDL 已就绪），
  异常直接抛（不同于 best-effort 钩子——schema 失败必须拦下启动）。

## 3. 批次 A 实施与验证记录

- **模块**：`backend/data/migrations/runner.py`（ensure_version_table /
  applied_versions / register_migration / run_pending_migrations）；
  `schema_version(version PK, name, applied_at)` 幂等建表。
- **接线**：init_db 既有 DDL 全部 commit 之后调用（此时基线 schema 就绪）；
  fail-fast 上抛（logger.exception + raise）。
- **测试**：+7 例（顺序应用 / 二次运行 no-op / 账本既有版本跳过 /
  版本号倒序拒绝（match 校验）/ 失败不留账本 / 迁移可执行 DDL /
  init_db 空注册表 no-op）。全局 MIGRATIONS 注册表用 save/restore
  fixture 隔离。
- **验证**：新测 7 例 + session_repo/message_search 回归 20 例全绿；
  ruff 全过；py38 护栏（compat_rewrite --check 0 变更 + AST 3.8）通过；
  baseline 同步（database.py 1858）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
