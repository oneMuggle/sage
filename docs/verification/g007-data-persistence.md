# g007: Data Persistence 验证映射

> 数据持久化契约：SQLite 数据库、备份策略、迁移管理。

---

**状态**: 🔴 未验证
**维护者**: @backend-team
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- SQLite 数据库 schema 设计与维护
- 数据库迁移（版本管理 + 数据迁移脚本）
- 自动备份与恢复
- 数据完整性约束（外键、唯一性、非空）
- 连接池管理

### 不负责

- API 端点实现（由 g006 负责）
- 前端缓存策略（由 g005 负责）
- 加密与密钥管理（由 g008 负责）

### 依赖

- 依赖 g006：API 层调用数据库操作
- 依赖 g008：敏感字段加密存储

---

## 2. 接口契约

### 2.1 Schema 版本管理

| 字段 | 说明 |
|------|------|
| 版本存储 | `schema_version` 表，单行记录当前版本号 |
| 迁移目录 | `backend/migrations/` |
| 命名规范 | `V{version}__{description}.sql`（如 `V1__initial_schema.sql`） |
| 迁移方向 | 每个迁移必须有对应的 rollback 脚本 |

### 2.2 核心表结构

| 表名 | 主要字段 | 外键 | 索引 |
|------|----------|------|------|
| `sessions` | `id`, `title`, `created_at`, `updated_at` | - | `idx_sessions_created` |
| `messages` | `id`, `session_id`, `role`, `content`, `created_at` | `session_id → sessions.id` | `idx_messages_session` |
| `skills` | `id`, `name`, `description`, `config` | - | `idx_skills_name` |
| `config` | `key`, `value`, `updated_at` | - | 主键 `key` |

### 2.3 数据库操作接口

| 操作 | 方法 | 事务 | 超时 |
|------|------|------|------|
| 读操作 | `db.query(sql, params)` | 否 | 5s |
| 写操作 | `db.execute(sql, params)` | 是 | 10s |
| 批量写入 | `db.batch_execute(operations)` | 是 | 30s |
| 迁移 | `db.migrate(target_version)` | 是 | 60s |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: Schema 版本一致

**定义**：运行时数据库的 `schema_version` 必须与代码期望的版本一致。不一致时拒绝启动。

**验证方法**：
```python
def verify_schema_version(db: Database, expected: int) -> bool:
    actual = db.query_one("SELECT version FROM schema_version")
    return actual['version'] == expected
```

**检查频率**：
- [x] 每次应用启动
- [ ] 每次迁移后

#### 不变量 2: 外键完整性

**定义**：所有外键引用的记录必须存在。SQLite 需启用 `PRAGMA foreign_keys = ON`。

**验证方法**：
```python
def verify_foreign_keys(db: Database) -> bool:
    violations = db.query("PRAGMA foreign_key_check")
    return len(violations) == 0
```

**检查频率**：
- [x] 每次写操作后（通过 SQLite pragma）
- [ ] 每天全量检查

#### 不变量 3: 备份频率

**定义**：每 24 小时至少产生一次自动备份，备份文件保留 7 天。

### 3.2 行为不变量

#### 迁移原子性

**定义**：单次迁移要么完全成功，要么完全回滚。不允许部分迁移状态。

**验证方法**：
```python
async def test_migration_atomicity():
    simulate_failure_during_migration(V2)
    assert db.get_schema_version() == 1
    assert verify_foreign_keys(db)
```

#### WAL 模式一致性

**定义**：SQLite 使用 WAL 模式，读写操作不互相阻塞。

### 3.3 性能不变量

#### 查询延迟 P95 < 50ms

**定义**：单表查询 95% 延迟 < 50ms（数据量 < 100K 行）。

#### 备份不阻塞写入

**定义**：在线备份期间，写操作延迟增加 < 10%。

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: 数据库文件损坏

**触发条件**：磁盘空间不足、非正常关机、文件系统错误

**影响**：严重性致命，所有数据操作失败

**检测方式**：`PRAGMA integrity_check` 失败

**恢复策略**：
1. 停止应用，避免进一步损坏
2. 尝试 `VACUUM` 修复
3. 修复失败则从最近备份恢复
4. 重放 WAL 中的事务（如有）

### 4.2 失败模式 2: 迁移失败

**触发条件**：迁移脚本有语法错误、数据不满足新约束、迁移中途断电

**恢复策略**：自动回滚到迁移前版本，记录失败原因到日志，通知用户手动处理

### 4.3 失败模式 3: 磁盘空间不足

**检测方式**：磁盘使用率 > 90%

**恢复策略**：清理过期备份，执行 `VACUUM` 回收空间，告警通知用户

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/unit/database/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/unit/database/ -v
```

**覆盖范围**：Schema 创建与迁移、外键约束、事务行为、连接池管理

### 5.2 集成测试

**位置**：`tests/integration/database/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/integration/database/ -v
```

**覆盖范围**：端到端数据流、备份与恢复、并发读写

### 5.3 迁移测试

**位置**：`tests/migrations/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/migrations/ -v
```

**覆盖范围**：每个迁移的前向 + 回滚、跨版本迁移（V1 → V5）、迁移幂等性

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 查询延迟 P95 | 直方图 | < 50ms | > 200ms | Prometheus |
| 活跃连接数 | 仪表 | < 10 | > 50 | Prometheus |
| 数据库大小 | 仪表 | < 500MB | > 1GB | 定时检查 |
| 备份新鲜度 | 仪表 | < 24h | > 48h | 定时检查 |
| 磁盘使用率 | 百分比 | < 70% | > 90% | 系统监控 |

### 6.2 健康检查

**端点**：`/health/database`

**检查项**：`PRAGMA integrity_check` 通过、Schema 版本一致、外键完整性、备份在有效期内

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| 迁移测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| Schema 版本一致 | ❌ | - |
| 外键完整性 | ❌ | - |
| 备份频率 | ❌ | - |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @backend-team |

---

## 9. 参考

- [SQLite 文档](https://www.sqlite.org/docs.html)
- [SQLite WAL 模式](https://www.sqlite.org/wal.html)
- [数据库代码](../../backend/database/)
- [迁移脚本](../../backend/migrations/)
- [数据库测试](../../tests/unit/database/)
