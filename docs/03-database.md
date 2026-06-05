# Sage - 数据库设计

## 3.1 数据库概览

### 3.1.1 数据库架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         Sage Data Store                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐           ┌─────────────────┐            │
│   │     SQLite      │           │    ChromaDB     │            │
│   │   (关系型数据)   │           │   (向量存储)     │            │
│   ├─────────────────┤           ├─────────────────┤            │
│   │  sessions      │           │  memories       │            │
│   │  messages       │           │  (语义记忆)      │            │
│   │  memories       │           │                 │            │
│   │  skills         │           │                 │            │
│   │  preferences    │           │                 │            │
│   │  evolution_log  │           │                 │            │
│   └─────────────────┘           └─────────────────┘            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 3.1.2 SQLite 表清单

| 表名              | 说明         | 主键 |
| ----------------- | ------------ | ---- |
| sessions          | 会话表       | id   |
| messages          | 消息表       | id   |
| memories_episodic | 情景记忆表   | id   |
| skills            | 技能表       | id   |
| preferences       | 用户偏好表   | key  |
| evolution_log     | 进化日志表   | id   |
| tool_usage        | 工具使用记录 | id   |

---

## 3.2 表结构详细设计

### 3.2.1 会话表 (sessions)

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '新对话',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    last_message_at INTEGER,
    message_count INTEGER DEFAULT 0,
    metadata TEXT,  -- JSON: {model, provider, tags}

    -- 统计信息
    total_tokens INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0,

    -- 状态
    is_pinned INTEGER DEFAULT 0,
    isarchived INTEGER DEFAULT 0,

    -- 父会话 (用于分支)
    parent_id TEXT REFERENCES sessions(id),

    -- 索引
    INDEX idx_sessions_updated (updated_at DESC),
    INDEX idx_sessions_pinned (is_pinned)
);
```

**说明**:

- `id`: UUID v4
- `title`: 自动生成或用户指定
- `metadata`: 存储模型选择、标签等
- `parent_id`: 支持会话分支

### 3.2.2 消息表 (messages)

```sql
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,

    -- 消息内容
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,

    -- AI 特定字段
    model TEXT,
    provider TEXT,
    finish_reason TEXT,

    -- Token 统计
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,

    -- 工具调用
    tool_calls TEXT,  -- JSON: [{name, args, result}]
    tool_call_id TEXT,

    -- 时间戳
    created_at INTEGER NOT NULL,
    latency_ms INTEGER,

    -- 索引
    INDEX idx_messages_session (session_id, created_at)
);
```

**说明**:

- `role`: 遵循 OpenAI 格式
- `tool_calls`: 存储工具调用链
- `latency_ms`: 响应延迟统计

### 3.2.3 情景记忆表 (memories_episodic)

```sql
CREATE TABLE memories_episodic (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,

    -- 记忆内容
    content TEXT NOT NULL,
    summary TEXT,  -- AI 生成的摘要

    -- 元数据
    memory_type TEXT DEFAULT 'conversation',
    importance INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),

    -- 来源追踪
    source TEXT DEFAULT 'auto',  -- 'auto' | 'manual' | 'skill'
    tags TEXT,  -- JSON: ["工作", "编程"]

    -- 时间戳
    created_at INTEGER NOT NULL,
    accessed_at INTEGER,
    access_count INTEGER DEFAULT 0,

    -- 情感/情绪标记
    sentiment TEXT,  -- 'positive' | 'neutral' | 'negative'

    -- 有效性
    is_valid INTEGER DEFAULT 1,
    expires_at INTEGER,  -- TTL, NULL 表示永不过期

    -- 索引
    INDEX idx_episodic_importance (importance DESC),
    INDEX idx_episodic_created (created_at DESC),
    INDEX idx_episodic_session (session_id)
);

-- FTS5 全文搜索
CREATE VIRTUAL TABLE memories_episodic_fts USING fts5(content, summary);
```

### 3.2.4 技能表 (skills)

```sql
CREATE TABLE skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    version TEXT NOT NULL DEFAULT '1.0.0',

    -- 技能定义
    description TEXT,
    triggers TEXT,  -- JSON: ["写代码", "编程"]
    code TEXT NOT NULL,

    -- 技能元数据
    author TEXT,
    homepage TEXT,
    icon TEXT,

    -- 权限
    permissions TEXT,  -- JSON: ["file:read", "terminal"]

    -- 状态
    is_enabled INTEGER DEFAULT 1,
    is_builtin INTEGER DEFAULT 0,

    -- 统计
    usage_count INTEGER DEFAULT 0,
    success_count INTEGER DEFAULT 0,
    last_used_at INTEGER,

    -- 版本
    created_at INTEGER NOT NULL,
    updated_at INTEGER,

    -- 索引
    INDEX idx_skills_enabled (is_enabled),
    INDEX idx_skills_name (name)
);
```

### 3.2.5 用户偏好表 (preferences)

```sql
CREATE TABLE preferences (
    key TEXT PRIMARY KEY,

    -- 值
    value TEXT NOT NULL,
    value_type TEXT DEFAULT 'string',  -- 'string' | 'number' | 'boolean' | 'json'

    -- 元数据
    description TEXT,
    category TEXT DEFAULT 'general',  -- 'general' | 'model' | 'ui' | 'privacy'

    -- 变更追踪
    created_at INTEGER NOT NULL,
    updated_at INTEGER,

    -- 索引
    INDEX idx_preferences_category (category)
);
```

**预设偏好项**:

| key                         | 类型    | 默认值          | 说明           |
| --------------------------- | ------- | --------------- | -------------- |
| model                       | string  | "gpt-3.5-turbo" | 默认模型       |
| temperature                 | number  | 0.7             | 默认温度       |
| max_tokens                  | number  | 4096            | 最大 Token     |
| theme                       | string  | "light"         | 主题           |
| language                    | string  | "zh-CN"         | 语言           |
| memory_importance_threshold | number  | 5               | 记忆重要性阈值 |
| evolution_enabled           | boolean | true            | 启用进化       |

### 3.2.6 进化日志表 (evolution_log)

```sql
CREATE TABLE evolution_log (
    id TEXT PRIMARY KEY,

    -- 进化类型
    evolution_type TEXT NOT NULL,  -- 'summary' | 'prune' | 'learn' | 'optimize'

    -- 详情
    description TEXT NOT NULL,
    before_state TEXT,  -- JSON
    after_state TEXT,  -- JSON

    -- 触发条件
    trigger_type TEXT,  -- 'scheduled' | 'manual' | 'threshold'
    trigger_condition TEXT,

    -- 结果
    status TEXT DEFAULT 'pending',  -- 'pending' | 'success' | 'failed'
    error_message TEXT,

    -- Token 消耗
    tokens_used INTEGER,

    -- 时间戳
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);
```

### 3.2.7 工具使用记录表 (tool_usage)

```sql
CREATE TABLE tool_usage (
    id TEXT PRIMARY KEY,

    -- 关联
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,

    -- 工具信息
    tool_name TEXT NOT NULL,
    tool_args TEXT,  -- JSON
    tool_result TEXT,

    -- 执行结果
    status TEXT DEFAULT 'success',  -- 'success' | 'failed' | 'skipped'
    error_message TEXT,
    duration_ms INTEGER,

    -- 时间戳
    created_at INTEGER NOT NULL
);
```

---

## 3.3 ChromaDB 向量存储

### 3.3.1 Collection 设计

```python
# backend/data/vector_store.py
from chromadb.config import Settings
import chromadb

class VectorStore:
    def __init__(self, persist_dir: str):
        self.client = chromadb.Client(Settings(
            persist_directory=persist_dir,
            anonymized_telemetry=False
        ))

    def get_memories_collection(self):
        """语义记忆集合"""
        return self.client.get_or_create_collection(
            name="semantic_memories",
            metadata={"description": "Sage 语义记忆向量存储"}
        )

    def get_knowledge_collection(self):
        """知识库集合"""
        return self.client.get_or_create_collection(
            name="knowledge",
            metadata={"description": "Sage 知识库向量存储"}
        )
```

### 3.3.2 Collection Schema

**semantic_memories Collection**:

| 字段      | 类型        | 说明                                 |
| --------- | ----------- | ------------------------------------ |
| id        | string      | UUID                                 |
| embedding | float[1536] | OpenAI embedding                     |
| document  | string      | 原文                                 |
| metadata  | dict        | {type, importance, created_at, tags} |

**knowledge Collection**:

| 字段      | 类型        | 说明                        |
| --------- | ----------- | --------------------------- |
| id        | string      | UUID                        |
| embedding | float[1536] | OpenAI embedding            |
| document  | string      | 知识内容                    |
| metadata  | dict        | {source, topic, confidence} |

---

## 3.4 数据库迁移

### 3.4.1 迁移策略

```python
# backend/data/migrations.py
MIGRATIONS = [
    {
        "version": 1,
        "name": "initial_schema",
        "up": [
            "CREATE TABLE sessions (...)",
            "CREATE TABLE messages (...)",
        ]
    },
    {
        "version": 2,
        "name": "add_evolution_log",
        "up": [
            "CREATE TABLE evolution_log (...)",
        ]
    },
]
```

### 3.4.2 迁移执行

```python
def run_migrations(conn: sqlite3.Connection, target_version: int):
    current = get_current_version(conn)

    for migration in MIGRATIONS:
        if migration["version"] > current and migration["version"] <= target_version:
            with conn:
                for sql in migration["up"]:
                    conn.execute(sql)
            update_version(conn, migration["version"])
```

---

## 3.5 数据备份

### 3.5.1 备份策略

| 备份类型 | 频率       | 保留数量 | 位置     |
| -------- | ---------- | -------- | -------- |
| 自动备份 | 每 10 分钟 | 5        | 同目录   |
| 每日备份 | 每天 3:00  | 7        | backup/  |
| 手动备份 | 用户触发   | 无限制   | 用户指定 |

### 3.5.2 备份实现

```python
# backend/data/backup.py
import shutil
from datetime import datetime
from pathlib import Path

class BackupManager:
    def __init__(self, db_path: Path, backup_dir: Path):
        self.db_path = db_path
        self.backup_dir = backup_dir

    def auto_backup(self):
        """自动备份"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"auto_{timestamp}.db"

        shutil.copy2(self.db_path, backup_path)
        self.clean_old_backups()

        return backup_path

    def clean_old_backups(self):
        """清理旧备份"""
        backups = sorted(self.backup_dir.glob("auto_*.db"))
        for old in backups[:-5]:  # 保留最近 5 个
            old.unlink()
```

---

## 3.6 索引优化

### 3.6.1 查询优化

```sql
-- 高频查询索引
CREATE INDEX idx_messages_session_time ON messages(session_id, created_at DESC);
CREATE INDEX idx_memories_importance ON memories_episodic(importance DESC, created_at DESC);
CREATE INDEX idx_sessions_active ON sessions(isarchived, updated_at DESC);

-- FTS 索引
CREATE VIRTUAL TABLE messages_fts USING fts5(content);
CREATE VIRTUAL TABLE memories_fts USING fts5(content, summary);
```

### 3.6.2 查询示例

```python
# 获取会话消息 (带分页)
def get_session_messages(session_id: str, limit: int = 50, offset: int = 0):
    return """
        SELECT * FROM messages
        WHERE session_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, [session_id, limit, offset]

# 搜索记忆 (按重要性排序)
def search_memories(query: str, min_importance: int = 5):
    return """
        SELECT * FROM memories_episodic
        WHERE content LIKE ? AND importance >= ? AND is_valid = 1
        ORDER BY importance DESC, access_count DESC
        LIMIT 20
    """, [f"%{query}%", min_importance]
```

---

## 3.7 数据库连接池

### 3.7.1 连接管理

```python
# backend/data/database.py
import sqlite3
from contextlib import contextmanager
from queue import Queue, Empty
from typing import Generator

class DatabasePool:
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self._pool = Queue(maxsize=pool_size)
        self._init_pool()

    def _init_pool(self):
        for _ in range(self._pool.maxsize):
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._pool.put(conn)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        try:
            conn = self._pool.get(timeout=5)
        except Empty:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)

        try:
            yield conn
        finally:
            if not self._pool.full():
                self._pool.put(conn)
```

---

_文档版本: v1.0_
