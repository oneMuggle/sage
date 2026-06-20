# g001: 记忆系统 (Memory System) 验证映射

> Sage 三层记忆系统 — 工作记忆 (WorkingMemory) / 情景记忆 (EpisodicMemory) / 语义记忆 (SemanticMemory)。
> 由 `MemoryManager` 统一管理门面，`ConsolidationPipeline` 负责 LLM 辅助压缩。

---

**状态**: 🔴 未验证  
**维护者**: @backend-team  
**最后更新**: 2026-06-19

---

## 1. 范围与职责

### 负责

- 职责 1：**工作记忆管理** — 基于 `collections.deque` 的滑动窗口，管理当前对话上下文（max_size=20，max_tokens=4000）
- 职责 2：**情景记忆持久化** — 基于 SQLite `memories_episodic` 表的事件序列存储，支持重要性评分 (1-10)、标签、访问计数、软删除
- 职责 3：**语义记忆与全文搜索** — 基于 SQLite FTS5 的知识和概念存储，支持 `MATCH` 全文检索和 `LIKE` 回退搜索
- 职责 4：**记忆压缩与归档** — `ConsolidationPipeline` 将工作记忆摘要压缩后存入情景记忆，支持 LLM 辅助和启发式回退
- 职责 5：**统一检索门面** — `MemoryManager.recall()` 跨三层记忆检索并汇总结果

### 不负责

- 非职责 1：对话循环 / LLM 调用（由 g004-agent-orchestration 负责）
- 非职责 2：会话 / 消息的 CRUD 持久化（由 `StoragePort` / `SqliteStorageAdapter` 负责）
- 非职责 3：用户偏好学习 / 进化任务调度（由 `scheduler/evolution.py` 负责）

### 依赖

- 依赖 `backend.data.database.Database`：SQLite 连接和 WAL 模式管理
- 依赖 `backend.core.legacy.llm_client.LLMClient`（可选）：`ConsolidationPipeline` 的 LLM 辅助摘要生成

---

## 2. 接口契约

### 2.1 输入断言

| 参数 | 类型 | 约束 | 验证方法 |
|------|------|------|----------|
| `content` (save/remember) | `str` | 非空字符串 | `assert isinstance(content, str) and len(content) > 0` |
| `importance` (episodic save) | `int` | 1-10 整数 | `assert 1 <= importance <= 10` |
| `memory_type` (memorize) | `str` | `'working'` / `'episodic'` / `'semantic'` / `'auto'` | `assert memory_type in ('working', 'episodic', 'semantic', 'auto')` |
| `limit` (recall/search) | `int` | > 0，< 1000 | `assert 0 < limit < 1000` |
| `query` (recall/search) | `str` | 可以为空（返回最近记忆） | `assert isinstance(query, str)` |
| `memory_id` (delete) | `str` | 非空 | `assert memory_id and len(memory_id) > 0` |

### 2.2 输出断言

| 返回值 | 类型 | 约束 | 验证方法 |
|--------|------|------|----------|
| `save()` → `str` | `str` | UUID4 格式 | `uuid.UUID(memory_id)` 不抛异常 |
| `recall()` → `dict` | `dict[str, list[dict]]` | 包含 `working`, `episodic`, `semantic` 三个键 | `assert set(result.keys()) == {'working', 'episodic', 'semantic'}` |
| `get_context()` → `str` | `str` | UTF-8 编码，可为空串 | `assert isinstance(result, str)` |
| `search_memories()` → `list` | `list[dict]` | 每个 dict 含 `content` 或 `id` 键 | `assert all('content' in r or 'id' in r for r in result)` |
| `get_stats()` → `dict` | `dict[str, dict]` | 包含 `working`, `episodic`, `semantic` 子字典 | `assert all(k in result for k in ('working', 'episodic', 'semantic'))` |

### 2.3 错误处理

| 错误场景 | 错误类型 | 处理方式 |
|----------|----------|----------|
| 情景记忆 SQLite 不可用 | `sqlite3.OperationalError` | `MemoryManager.get_stats()` 用 `contextlib.suppress` 静默处理 |
| 语义记忆 FTS5 搜索失败 | `Exception` | 自动回退到 `_search_like()` — 使用 SQL `LIKE` 子句 |
| LLM 摘要生成失败 | `Exception` | `ConsolidationPipeline` 回退到启发式策略 `_fallback_summary` |
| 不支持的记忆类型删除 | `ValueError`（日志警告） | `delete_memory()` 返回 `False` |
| 空消息列表压缩 | 返回 `None` | `compress_working_memory([])` → `None` |

---

## 3. 不变量约束

### 3.1 数据不变量

#### 不变量 1: 记忆 ID 唯一性

**定义**：每条记忆（episodic / semantic）的 `id` 字段是 UUID4，在各自表中唯一。

**验证方法**：
```python
def verify_memory_id_uniqueness(db) -> bool:
    """验证所有记忆表中的 ID 唯一性"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, COUNT(*) as cnt FROM memories_episodic
        WHERE is_valid = 1 GROUP BY id HAVING cnt > 1
    """)
    if cursor.fetchall():
        return False
    cursor.execute("""
        SELECT id, COUNT(*) as cnt FROM memories_semantic
        GROUP BY id HAVING cnt > 1
    """)
    return len(cursor.fetchall()) == 0
```

**检查频率**：
- [x] 每次写操作后（由 SQLite PRIMARY KEY 约束保证）
- [ ] 每天（全量校验）

**测试用例**：
```python
def test_memory_id_uniqueness(db):
    """测试 save() 每次返回不同 UUID"""
    from backend.memory.episodic import EpisodicMemory

    episodic = EpisodicMemory(db)
    id1 = episodic.save(content="test1", importance=5)
    id2 = episodic.save(content="test2", importance=5)
    assert id1 != id2
    assert verify_memory_id_uniqueness(db)
```

#### 不变量 2: 工作记忆容量约束

**定义**：`WorkingMemory.messages` 的长度不超过 `max_size`（默认 20），淘汰后 `total_tokens` 恢复至合理范围。

**验证方法**：
```python
def verify_working_memory_capacity(wm: WorkingMemory) -> bool:
    """验证工作记忆容量约束"""
    return len(wm.messages) <= wm.max_size
```

**检查频率**：
- [x] 每次 `add()` 调用后

**测试用例**：
```python
def test_working_memory_capacity():
    """测试工作记忆滑动窗口淘汰"""
    from backend.memory.working import WorkingMemory

    wm = WorkingMemory(max_size=5, max_tokens=4000)
    for i in range(10):
        wm.add({"role": "user", "content": f"message {i}"})
    assert len(wm.messages) <= 5
    assert verify_working_memory_capacity(wm)
```

#### 不变量 3: 语义记忆 FTS 同步

**定义**：`memories_semantic` 主表与 `memories_semantic_fts` 虚拟表的行数一致。

**验证方法**：
```python
def verify_fts_sync(db) -> bool:
    """验证主表与 FTS 表行数一致"""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM memories_semantic")
    main_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM memories_semantic_fts")
    fts_count = cursor.fetchone()[0]
    return main_count == fts_count
```

**检查频率**：
- [x] 每次写操作后
- [ ] 每小时（一致性审计）

**测试用例**：
```python
def test_fts_sync_after_save_and_delete(db):
    """测试 save/delete 后 FTS 表同步"""
    from backend.memory.semantic import SemanticMemory

    sm = SemanticMemory(db)
    mid = sm.save(content="Python 编程", tags=["coding"])
    assert verify_fts_sync(db)
    sm.delete(mid)
    assert verify_fts_sync(db)
```

### 3.2 行为不变量

#### 幂等性

**定义**：`search()` 操作是幂等的 — 相同查询多次调用返回一致的结果集。

**验证方法**：
```python
def test_search_idempotency(db):
    """搜索幂等性：多次搜索同一查询结果一致"""
    from backend.memory.manager import MemoryManager
    from backend.memory.working import WorkingMemory
    from backend.memory.episodic import EpisodicMemory
    from backend.memory.semantic import SemanticMemory

    mm = MemoryManager(WorkingMemory(), EpisodicMemory(db), SemanticMemory(db))
    mm.remember("Sage 使用 SQLite 数据库", {"importance": 7})

    result1 = mm.search_memories("SQLite", limit=5)
    result2 = mm.search_memories("SQLite", limit=5)
    assert len(result1) == len(result2)
    assert result1[0]["content"] == result2[0]["content"]
```

#### 自动分类一致性

**定义**：`_classify_memory_type()` 的分类规则必须满足：importance ≥ 8 → semantic；短内容 (<200 chars) 且 importance < 5 → working；其余 → episodic。

**验证方法**：
```python
def test_auto_classification():
    """测试自动记忆分类规则"""
    from backend.memory.manager import MemoryManager
    from backend.memory.working import WorkingMemory
    from unittest.mock import MagicMock

    db = MagicMock()
    mm = MemoryManager(WorkingMemory(), MagicMock(), MagicMock())

    assert mm._classify_memory_type("短内容", importance=3) == "working"
    assert mm._classify_memory_type("短内容", importance=8) == "semantic"
    assert mm._classify_memory_type("长内容" * 50, importance=5) == "episodic"
    assert mm._classify_memory_type("短内容", importance=5) == "episodic"
```

### 3.3 性能不变量

#### 搜索延迟 P95 < 100ms

**定义**：语义记忆 FTS5 搜索 P95 延迟低于 100ms（1000 条记忆规模下）。

**验证方法**：
```python
import time
import numpy as np

def test_search_latency_p95(db):
    """测试搜索延迟 P95 < 100ms"""
    from backend.memory.semantic import SemanticMemory

    sm = SemanticMemory(db)
    for i in range(1000):
        sm.save(content=f"知识条目 {i}", tags=[f"tag{i % 10}"])

    latencies = []
    for _ in range(100):
        start = time.perf_counter()
        sm.search("知识", limit=10)
        latencies.append((time.perf_counter() - start) * 1000)

    p95 = np.percentile(latencies, 95)
    assert p95 < 100, f"P95 延迟 {p95:.1f}ms 超过 100ms 阈值"
```

---

## 4. 失败模式与恢复

### 4.1 失败模式 1: SQLite 数据库不可用

**触发条件**：
- SQLite 文件损坏或磁盘满
- 并发写入导致长时间锁等待（busy_timeout=5000ms 已设）

**影响**：
- 严重性：高
- 影响范围：情景记忆和语义记忆完全不可写，工作记忆（内存）不受影响

**检测方式**：
```python
def detect_sqlite_failure(db) -> bool:
    """检测 SQLite 是否可用"""
    try:
        conn = db.get_connection()
        conn.execute("SELECT 1")
        return False
    except Exception:
        return True
```

**恢复策略**：
1. 工作记忆继续运作（纯内存），对话不中断
2. 日志记录错误，`get_stats()` 中 episodic/semantic 计数返回 0
3. 应用重启时 SQLite 重新初始化（WAL 模式自动恢复）

**验证测试**：
```python
def test_sqlite_failure_degradation():
    """测试 SQLite 故障时工作记忆降级运行"""
    from backend.memory.manager import MemoryManager
    from backend.memory.working import WorkingMemory
    from unittest.mock import MagicMock

    broken_db = MagicMock()
    broken_db.get_connection.side_effect = Exception("disk full")

    wm = WorkingMemory()
    mm = MemoryManager(wm, broken_db, broken_db)

    # 工作记忆仍正常
    mm.add_to_working("user", "hello")
    assert len(wm.messages) == 1

    # get_stats 静默处理失败
    stats = mm.get_stats()
    assert stats["working"]["message_count"] == 1
```

### 4.2 失败模式 2: FTS5 全文搜索失败

**触发条件**：
- FTS5 查询包含特殊字符导致 `MATCH` 语法错误
- FTS5 虚拟表损坏

**影响**：
- 严重性：中
- 影响范围：仅语义记忆搜索退化为 LIKE 搜索

**恢复策略**：
1. `SemanticMemory.search()` 中 `try/except` 捕获异常
2. 自动回退到 `_search_like()` — SQL `LIKE` 子句
3. 日志记录回退事件

**验证测试**：
```python
def test_fts_fallback_to_like(db):
    """测试 FTS5 失败时回退到 LIKE 搜索"""
    from backend.memory.semantic import SemanticMemory

    sm = SemanticMemory(db)
    sm.save(content="Python 编程入门", tags=["python"])

    # 包含 FTS5 特殊字符的查询应回退到 LIKE
    results = sm.search('Python "入门', limit=5)
    assert len(results) >= 1
```

### 4.3 失败模式 3: LLM 摘要生成失败

**触发条件**：
- LLM API 不可用或超时
- 返回内容为空

**影响**：
- 严重性：低
- 影响范围：`ConsolidationPipeline` 使用回退策略，不影响系统运行

**恢复策略**：
1. `compress_working_memory()` 自动回退到 `_fallback_summary()`
2. 提取用户消息首条内容的前 80 字符作为简单摘要

**验证测试**：
```python
def test_consolidation_fallback_without_llm():
    """测试无 LLM 时的回退摘要策略"""
    from backend.memory.consolidation import ConsolidationPipeline

    pipe = ConsolidationPipeline(llm_client=None)
    messages = [
        {"role": "user", "content": "帮我写一个排序算法"},
        {"role": "assistant", "content": "好的，以下是冒泡排序..."},
    ]
    summary = pipe.compress_working_memory(messages)
    assert summary is not None
    assert len(summary) > 0
```

---

## 5. 验证方法

### 5.1 单元测试

**位置**：`tests/verification/g001/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/verification/g001/ -v --cov=backend/memory
```

**覆盖范围**：
- [ ] WorkingMemory 滑动窗口淘汰 + token 估算
- [ ] EpisodicMemory save/search/delete/get_by_id/count
- [ ] SemanticMemory save/search(FTS5)/search(LIKE fallback)/delete/update_tags
- [ ] MemoryManager 自动分类逻辑 + recall 跨层检索
- [ ] ConsolidationPipeline LLM 回退 + extract_key_facts

### 5.2 集成测试

**位置**：`tests/integration/g001/`

**运行命令**：
```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest tests/integration/g001/ -v
```

**覆盖范围**：
- [ ] 三层记忆端到端写入和检索
- [ ] FTS5 与主表同步一致性
- [ ] 记忆压缩 → 情景记忆归档完整流程

### 5.3 属性测试

**位置**：`tests/property/g001/`

**使用的库**：`hypothesis`

**测试的属性**：
- [ ] 搜索幂等性：同一查询多次搜索返回相同结果集
- [ ] 写入后必可检索：save() 后 search() 包含新记忆
- [ ] 删除后不可检索：delete() 后 search() 不包含已删记忆
- [ ] 工作记忆容量上限：add() N 次后 len(messages) ≤ max_size

### 5.4 性能测试

**位置**：`tests/performance/g001/`

**测试的指标**：
- [ ] 搜索延迟 P95 < 100ms（1000 条记忆规模）
- [ ] 写入吞吐量 > 50 writes/s
- [ ] 工作记忆 add/get_context 延迟 < 1ms

---

## 6. 监控指标

### 6.1 运行时指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 搜索延迟 P95 | 直方图 | < 100ms | > 200ms | Prometheus |
| 记忆写入延迟 | 直方图 | < 50ms | > 100ms | Prometheus |
| 工作记忆消息数 | 仪表 | < 20 | > 20 | 日志 |
| FTS 回退率 | 计数器 | < 5% | > 20% | 日志 |

### 6.2 业务指标

| 指标 | 类型 | 目标值 | 告警阈值 | 监控方式 |
|------|------|--------|----------|----------|
| 记忆召回命中率 | 比率 | > 60% | < 30% | 搜索返回非空结果的比例 |
| 记忆压缩频率 | 计数器 | 按需 | 每分钟 > 5 次 | ConsolidationPipeline 调用计数 |

### 6.3 健康检查

**端点**：`GET /health/memory`

**返回格式**：
```json
{
  "status": "healthy",
  "checks": {
    "sqlite": "ok",
    "fts5_sync": "ok",
    "working_memory": {"messages": 5, "tokens": 1200, "max_tokens": 4000}
  },
  "stats": {
    "episodic_total": 156,
    "semantic_total": 42
  },
  "timestamp": "2026-06-19T12:00:00Z"
}
```

---

## 7. 验证状态

### 7.1 测试覆盖率

| 验证类型 | 状态 | 覆盖率 | 最后运行 |
|----------|------|--------|----------|
| 单元测试 | 🔴 | 0% | - |
| 集成测试 | 🔴 | 0% | - |
| 性能测试 | 🔴 | 0% | - |
| 属性测试 | 🔴 | 0% | - |

### 7.2 不变量验证

| 不变量 | 状态 | 最后验证 |
|--------|------|----------|
| 记忆 ID 唯一性 | ❌ | - |
| 工作记忆容量约束 | ❌ | - |
| FTS 表同步一致性 | ❌ | - |
| 搜索幂等性 | ❌ | - |
| 自动分类一致性 | ❌ | - |

### 7.3 失败模式测试

| 失败模式 | 检测测试 | 恢复测试 | 状态 |
|----------|----------|----------|------|
| SQLite 不可用 | ❌ | ❌ | 🔴 |
| FTS5 搜索失败 | ❌ | ❌ | 🔴 |
| LLM 摘要生成失败 | ❌ | ❌ | 🔴 |

---

## 8. 变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-19 | 初始版本 | @backend-team |

---

## 9. 参考

- [MemoryManager 源码](../../backend/memory/manager.py) — 统一门面
- [WorkingMemory 源码](../../backend/memory/working.py) — 工作记忆
- [EpisodicMemory 源码](../../backend/memory/episodic.py) — 情景记忆
- [SemanticMemory 源码](../../backend/memory/semantic.py) — 语义记忆 + FTS5
- [ConsolidationPipeline 源码](../../backend/memory/consolidation.py) — 压缩管道
- [数据库 Schema](../../backend/data/database.py) — SQLite 表定义
- [配置参考](../../backend/config.yaml) — `memory` 节
