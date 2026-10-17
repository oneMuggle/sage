# scheduled_tasks.json → SQLite 迁移

> Phase 2 of 长时任务健壮性优化

## 背景与目标

### 问题陈述

当前 `SchedulerService` 使用 JSON 文件持久化定时任务：
- 无事务保护：写入中途崩溃 → 文件损坏 → 全部任务丢失
- 无并发安全：虽有 `threading.Lock`，但 JSON 原子写入仅靠 `.tmp` + `rename`，无法防止读取时文件正被覆盖
- 与编排层 SQLite 仓储技术栈割裂：运维复杂度增加
- 无备份机制：文件损坏无恢复路径

### 目标

- 新建 `ScheduledTaskRepository`（SQLite），复用 `Database` 共享连接 + `_SQLITE_LOCK`
- 迁移脚本：启动时若 SQLite 表为空且 JSON 存在，自动从 JSON 导入
- 保留 JSON 作为备份（不删除原文件，仅标记已迁移）
- 获得 WAL、事务、备份能力
- 无 API 变更，对上层完全透明

---

## 涉及的文件与模块

| 文件 | 修改内容 |
|---|---|
| `backend/data/database.py` | 新增 `scheduled_tasks` 表 DDL |
| `backend/services/scheduler_repository.py` | 新增：`ScheduledTaskRepository` 类 |
| `backend/services/scheduler.py` | 改用 `ScheduledTaskRepository` 替代 JSON 读写 |
| `backend/tests/test_scheduled_task_repository.py` | 新增：仓储层单元测试 |
| `backend/tests/unit/test_scheduler_migration.py` | 新增：JSON → SQLite 迁移测试 |

---

## 技术方案

### 1. SQLite 表结构

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('once', 'recurring')),
    schedule TEXT NOT NULL,  -- JSON-encoded
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    last_run INTEGER,
    next_run INTEGER,
    last_attempt INTEGER,
    last_status TEXT NOT NULL DEFAULT 'never',
    last_error TEXT,
    run_count INTEGER NOT NULL DEFAULT 0,
    max_runs INTEGER
);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_session
    ON scheduled_tasks(session_id);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
    ON scheduled_tasks(next_run) WHERE next_run IS NOT NULL;
```

配套一张迁移记账表——**不能**用「表是否为空」判断迁移是否做过：用户删光全部
任务后表为空，下次启动会从陈旧 JSON 备份把任务全部复活。

```sql
CREATE TABLE IF NOT EXISTS scheduler_migrations (
    source TEXT PRIMARY KEY,   -- JSON 存储路径
    migrated_at INTEGER NOT NULL,
    imported INTEGER NOT NULL DEFAULT 0
);
```

### 2. ScheduledTaskRepository

```python
class ScheduledTaskRepository:
    def __init__(self, db: Database):
        self.db = db

    def list_all(self) -> List[ScheduledTask]:
        ...

    def get(self, task_id: str) -> Optional[ScheduledTask]:
        ...

    def upsert(self, task: ScheduledTask) -> None:
        ...

    def delete(self, task_id: str) -> bool:
        ...
```

关键设计：
- 复用 `Database.get_connection()` 返回的 `_LockedConnection`（自动加锁）
- **dict 契约**：行结构 == `ScheduledTask.to_dict()`，仓储不 import dataclass
  （否则与 `backend/services/scheduler.py` 形成循环 import），JSON→SQLite
  因此是纯格式转换
- `schedule` 字段 JSON 编码存储（与现有 `to_dict()` 兼容）
- `enabled` 用 `INTEGER` (0/1)，读取时转 `bool`
- 不引入额外线程锁，所有访问经 `_SQLITE_LOCK`
- 写操作用 `BEGIN IMMEDIATE` 单事务（`upsert` / `bulk_upsert` / `delete`）

### 3. SchedulerService 改造

- `db` 为**可选**关键字参数（默认 `None`）：传则走 SQLite，不传则保持原 JSON
  行为 → 现有 28 处 `SchedulerService(store_path, ...)` 测试构造点零改动
- 新增 `_persist(task)` / `_persist_delete(task_id)`：把原先「全量重写 JSON」
  的 4 处调用改为定点写（SQLite 模式下每任务一次 upsert/delete，而非重写整个文件）
- 新增 `_load_from_repo()` / `_migrate_from_json()`
- `_load_from_disk()` / `_save_to_disk()` 保留，仅在 `db is None` 时生效
- `backend/main.py` lifespan 传 `db=get_database()`（该符号已在 132 行导入）

### 4. 迁移逻辑

```python
def _migrate_from_json(self) -> None:
    """首次启动时从 JSON 导入到 SQLite（幂等）。"""
    assert self._repository is not None
    source = str(self._store_path)
    if self._repository.has_migrated(source) or not self._store_path.exists():
        return
    try:
        raw = json.loads(self._store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("scheduled_tasks.json unreadable, starting empty: %s", exc)
        self._repository.mark_migrated(source, 0, int(time.time() * 1000))
        return
    if raw.get("version") != SCHEMA_VERSION:
        logger.warning("JSON schema mismatch, skipping migration")
        self._repository.mark_migrated(source, 0, int(time.time() * 1000))
        return
    importable = [item for item in raw.get("tasks", []) if _parses(item)]
    imported = self._repository.bulk_upsert(importable)
    self._repository.mark_migrated(source, imported, int(time.time() * 1000))
    logger.info("migrated %d tasks from JSON to SQLite", imported)
    # 不删除 JSON，保留为备份
```

**幂等标记而非空表判断**：损坏 JSON / 版本不符这两条早退分支同样要打标记，
否则每次启动都会重新解析坏文件。

---

## 实施步骤

- [x] **步骤 1**：`database.py` 新增 `scheduled_tasks` + `scheduler_migrations` 表 DDL
- [x] **步骤 2**：创建 `backend/services/scheduler_repository.py`
- [x] **步骤 3**：`scheduler.py` 改用仓储（`db` 可选参数 + `_persist`/`_persist_delete`），`main.py` 注入 `get_database()`
- [x] **步骤 4**：添加 JSON → SQLite 幂等迁移（`scheduler_migrations` 记账）
- [x] **步骤 5**：编写单元测试（仓储 10 例 + 迁移 11 例，21 passed）
- [x] **步骤 6**：运行全量测试确保无回归
      全量 11138 passed / 11 failed。11 个失败逐个归因：
      - 10 个（`cli/checks/test_port_*`、`test_git_tool`、`test_retry_resilience`、
        `test_skill_import`）在基线 commit `a2f3a6b49` 的独立 worktree 上原样复现
        → 存量环境性失败（端口占用 / git 仓库状态 / 用户级 `~/.sage/skills`），
        与本次改动无关
      - `test_curator_provenance::test_factory_creates_task` 隔离运行通过
        → 已知的测试顺序污染，非回归
      新增 21 例全绿，既有 72 例 scheduler/schedule_tool/audit_reliability 全绿
- [ ] **步骤 7**：提交 PR

---

## 风险评估

1. **迁移失败**：JSON 格式损坏 → 记录日志 + 打标记，启动空仓储，不阻塞后端
2. **任务复活**：靠 `scheduler_migrations` 标记而非空表判断（见步骤 4 说明）
3. **并发写入**：`_SQLITE_LOCK` 已保护，无额外风险
4. **API 兼容性**：`SchedulerService` 公共 API 与签名全部不变（`db` 为尾部默认参数），上层无感知
5. **测试兼容**：`db` 默认 `None` 走原 JSON 路径，28 处现有测试构造点零改动
6. **磁盘占用**：JSON 备份保留（按计划不删除），WAL 模式额外占 `-wal`/`-shm`

---

## 依赖

- 无外部依赖
- 复用现有 `Database` 基础设施
- 复用 `ScheduledTask` 数据类（`to_dict()` / `from_dict()`）
