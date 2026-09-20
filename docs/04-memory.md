# Sage - 记忆系统

## 4.1 记忆系统概述

### 4.1.1 设计理念

Sage 的记忆系统参考人类记忆的三层模型，结合 Hermes Agent 的实现经验:

```
┌─────────────────────────────────────────────────────────────┐
│                     Human Memory Model                        │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                 Sensory Memory                        │   │
│   │         (瞬时感知，稍纵即逝)                           │   │
│   └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                 Short-Term Memory                     │   │
│   │              (工作记忆，容量有限 7±2)                  │   │
│   └─────────────────────────────────────────────────────┘   │
│                           │                                 │
│                           ▼                                 │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                 Long-Term Memory                      │   │
│   │    ┌─────────────┐    ┌─────────────┐              │   │
│   │    │ Episodic   │    │ Semantic    │              │   │
│   │    │ (情景)      │    │ (语义)       │              │   │
│   │    └─────────────┘    └─────────────┘              │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 4.1.2 Sage 记忆架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       Sage Memory System                          │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                   Working Memory                         │   │
│   │              (当前对话上下文，在内存中)                   │   │
│   │                                                           │   │
│   │   • 最近 N 条消息                                         │   │
│   │   • 当前会话摘要                                          │   │
│   │   • 活跃实体/话题                                         │   │
│   │   • 临时变量                                              │   │
│   │                                                           │   │
│   │   容量: ~4000 tokens (可配置)                             │   │
│   │   淘汰: LRU + 重要性加权                                  │   │
│   └──────────────────────────┬──────────────────────────────┘   │
│                              │ 定时压缩                          │
│                              ▼                                   │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                   Episodic Memory                         │   │
│   │                 (情景记忆，SQLite 存储)                     │   │
│   │                                                           │   │
│   │   • 对话历史摘要                                          │   │
│   │   • 事件序列                                              │   │
│   │   • 用户偏好 (显式)                                       │   │
│   │   • 情感标记                                              │   │
│   │                                                           │   │
│   │   索引: importance + access_count + recency              │   │
│   │   TTL: 可配置，默认永不过期                                │   │
│   └──────────────────────────┬──────────────────────────────┘   │
│                              │ 定期归档                          │
│                              ▼                                   │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                   Semantic Memory                         │   │
│   │          (语义记忆，SQLite FTS5 + sqlite-vec)             │   │
│   │                                                           │   │
│   │   • 知识概念                                              │   │
│   │   • 用户画像                                             │   │
│   │   • 技能知识                                              │   │
│   │   • 事实性知识                                            │   │
│   │                                                           │   │
│   │   检索: FTS5 全文 + jieba 分词，LIKE 兜底                 │
│   │   更新: 版本控制，支持回滚                                 │   │
│   └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

> 注:早期文档中的 ChromaDB 方案已废弃，当前实现基于 SQLite(FTS5 全文 +
> jieba 中文分词 + sqlite-vec 向量)，见 `backend/memory/semantic.py`。
> 本章 4.2/4.3/4.4 的部分代码片段为早期设计稿，以仓库源码为准；
> 4.8 节描述的是已落地的 **作用域(scope)轴**。

---

## 4.2 记忆类型详解

### 4.2.1 Working Memory (工作记忆)

```python
# backend/memory/working.py
from dataclasses import dataclass, field
from typing import List, Optional
from collections import deque

@dataclass
class WorkingMemory:
    """工作记忆 - 当前对话上下文"""

    # 配置
    max_tokens: int = 4000
    max_messages: int = 20

    # 数据
    messages: deque = field(default_factory=lambda: deque(maxlen=20))
    session_summary: str = ""
    active_entities: List[str] = field(default_factory=list)
    temp_variables: dict = field(default_factory=dict)

    # 统计
    total_tokens: int = 0

    def add_message(self, role: str, content: str, tokens: int):
        """添加消息"""
        self.messages.append({
            "role": role,
            "content": content,
            "tokens": tokens,
            "timestamp": time.time()
        })
        self.total_tokens += tokens
        self._evict_if_needed()

    def _evict_if_needed(self):
        """LRU 淘汰"""
        while self.total_tokens > self.max_tokens and len(self.messages) > 1:
            old = self.messages.popleft()
            self.total_tokens -= old["tokens"]

    def get_context(self) -> List[dict]:
        """获取当前上下文"""
        return list(self.messages)

    def summarize(self) -> str:
        """生成摘要"""
        if not self.session_summary:
            return f"[{len(self.messages)} 条消息, {self.total_tokens} tokens]"
        return self.session_summary
```

**特点**:

- 存储在内存中，速度最快
- 基于 LRU 的自动淘汰
- 支持 Token 数量限制
- 可配置保留消息数量

### 4.2.2 Episodic Memory (情景记忆)

```python
# backend/memory/episodic.py
from dataclasses import dataclass
from typing import List, Optional
import sqlite3
import json

@dataclass
class EpisodicMemory:
    """情景记忆 - 事件序列和经历"""

    db: sqlite3.Connection

    async def save_conversation(
        self,
        session_id: str,
        messages: List[dict],
        summary: str,
        importance: int = 5
    ):
        """保存对话记忆"""
        cursor = self.db.cursor()

        # 生成摘要
        memory_content = self._generate_memory_content(session_id, messages)

        cursor.execute("""
            INSERT INTO memories_episodic
            (id, session_id, content, summary, memory_type, importance, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            session_id,
            memory_content,
            summary,
            "conversation",
            importance,
            int(time.time())
        ))

        self.db.commit()

    async def retrieve(
        self,
        query: str,
        limit: int = 5,
        min_importance: int = 3
    ) -> List[dict]:
        """检索相关记忆"""
        cursor = self.db.cursor()

        # 模糊匹配 + 重要性过滤
        cursor.execute("""
            SELECT * FROM memories_episodic
            WHERE content LIKE ?
            AND importance >= ?
            AND is_valid = 1
            ORDER BY importance DESC, access_count DESC, created_at DESC
            LIMIT ?
        """, (f"%{query}%", min_importance, limit))

        results = []
        for row in cursor.fetchall():
            memory = dict(row)
            # 更新访问统计
            self._update_access(memory["id"])
            results.append(memory)

        return results

    def _generate_memory_content(self, session_id: str, messages: List[dict]) -> str:
        """生成记忆内容"""
        lines = [f"会话 {session_id} 摘要:"]
        for msg in messages[-10:]:  # 最近 10 条
            role = msg.get("role", "unknown")
            content = msg.get("content", "")[:200]  # 截断
            lines.append(f"- [{role}]: {content}")
        return "\n".join(lines)
```

**特点**:

- SQLite 持久化存储
- 支持全文搜索 (FTS5)
- 重要性评分 (1-10)
- 访问计数优化
- TTL 支持

### 4.2.3 Semantic Memory (语义记忆)

```python
# backend/memory/semantic.py
from typing import List, Optional
import chromadb
from chromadb.config import Settings

@dataclass
class SemanticMemory:
    """语义记忆 - 知识和概念"""

    vector_store: chromadb.Client
    collection_name: str = "semantic_memories"

    def __post_init__(self):
        self.collection = self.vector_store.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Sage 语义记忆"}
        )

    async def store(
        self,
        content: str,
        metadata: dict,
        embedding: List[float] = None
    ):
        """存储语义记忆"""
        if embedding is None:
            embedding = await self._generate_embedding(content)

        self.collection.add(
            documents=[content],
            embeddings=[embedding],
            metadatas=[metadata],
            ids=[str(uuid.uuid4())]
        )

    async def retrieve(
        self,
        query: str,
        n_results: int = 5,
        filter_metadata: dict = None
    ) -> List[dict]:
        """检索语义记忆"""
        query_embedding = await self._generate_embedding(query)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=filter_metadata
        )

        memories = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                memories.append({
                    "content": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i]
                })

        return memories

    async def _generate_embedding(self, text: str) -> List[float]:
        """生成文本嵌入"""
        # TODO: 调用 OpenAI embedding API
        # 暂时使用占位符
        return [0.0] * 1536  # OpenAI ada-002 dimension
```

**特点**:

- SQLite FTS5 全文索引 + jieba 中文分词(向量侧由 sqlite-vec 承载)
- 高维语义相似度检索
- 支持元数据过滤(含 scope / project_key，见 4.8)
- 版本控制支持

---

## 4.3 记忆管理器

### 4.3.1 MemoryManager 核心

```python
# backend/memory/manager.py
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

class MemoryManager:
    """
    记忆管理器 - 统一管理三层记忆

    负责:
    1. 协调三层记忆的读写
    2. 记忆压缩和归档
    3. 记忆检索和召回
    4. 记忆重要性评估
    """

    def __init__(
        self,
        working: WorkingMemory,
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        config: dict
    ):
        self.working = working
        self.episodic = episodic
        self.semantic = semantic
        self.config = config

    async def remember(self, query: str, context: dict = None) -> str:
        """
        检索相关记忆，生成上下文

        Args:
            query: 查询文本
            context: 额外上下文

        Returns:
            格式化记忆上下文
        """
        results = []

        # 1. 语义记忆检索 (最相关)
        semantic_results = await self.semantic.retrieve(query, n_results=3)
        if semantic_results:
            results.append("【相关知识】")
            for mem in semantic_results:
                results.append(f"- {mem['content']}")

        # 2. 情景记忆检索
        episodic_results = await self.episodic.retrieve(query, limit=3)
        if episodic_results:
            results.append("\n【相关经历】")
            for mem in episodic_results:
                results.append(f"- {mem['summary']}")

        # 3. 当前会话上下文
        if context and context.get("session_id"):
            session_context = self.working.summarize()
            results.append(f"\n【当前会话】{session_context}")

        if not results:
            return ""

        return "\n".join(results)

    async def memorize(
        self,
        content: str,
        memory_type: str = "auto",
        importance: int = 5,
        metadata: dict = None
    ):
        """
        保存记忆

        Args:
            content: 记忆内容
            memory_type: 'working' | 'episodic' | 'semantic'
            importance: 重要性 1-10
            metadata: 额外元数据
        """
        if memory_type == "auto":
            # 自动判断记忆类型
            memory_type = self._classify_memory_type(content, importance)

        if memory_type == "episodic":
            await self.episodic.save(
                content=content,
                importance=importance,
                metadata=metadata
            )
        elif memory_type == "semantic":
            await self.semantic.store(
                content=content,
                metadata={**metadata, "importance": importance} if metadata else {"importance": importance}
            )
        elif memory_type == "working":
            self.working.add_message("system", content, tokens=len(content) // 4)

    def _classify_memory_type(self, content: str, importance: int) -> str:
        """自动分类记忆类型"""
        # 高重要性 → 语义记忆
        if importance >= 8:
            return "semantic"
        # 低重要性短记忆 → 工作记忆
        if len(content) < 200 and importance < 5:
            return "working"
        # 默认 → 情景记忆
        return "episodic"
```

### 4.3.2 记忆检索流程

```
User Query: "我在北京的工作"
    │
    ▼
┌────────────────────────────────────────────────────────────┐
│ 1. Query Processing                                         │
│    - 分词/清洗                                               │
│    - 实体识别: "北京" (地点), "工作" (主题)                  │
└────────────────────────────┬───────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────┐
│ 2. Multi-Source Retrieval                                    │
│                                                            │
│   ┌─────────────────┐                                     │
│   │ Semantic Search │  SQLite FTS5 + 向量检索               │
│   │ "北京 工作"     │  → 找到: "用户在北京工作过"           │
│   └────────┬────────┘                                     │
│            │                                               │
│   ┌─────────────────┐                                     │
│   │ Episodic Search │  SQLite FTS5 + 重要性过滤            │
│   │ "北京 工作"     │  → 找到: 对话中提及北京工作           │
│   └────────┬────────┘                                     │
│            │                                               │
│   ┌─────────────────┐                                     │
│   │ Working Memory  │  当前会话上下文                      │
│   │ 最近消息        │  → 找到: 刚才讨论的话题               │
│   └─────────────────┘                                     │
└────────────────────────────┬───────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────┐
│ 3. Result Fusion                                            │
│                                                            │
│    - 合并去重                                               │
│    - 重要性加权                                             │
│    - 时效性调整                                             │
│    - 生成上下文                                             │
└────────────────────────────┬───────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────┐
│ 4. Context Assembly                                         │
│                                                            │
│ 【相关知识】                                                │
│ - 用户曾在知乎工作，现在北京出差                             │
│                                                            │
│ 【相关经历】                                                │
│ - 上周讨论过换工作的事                                      │
│                                                            │
│ 【当前会话】                                                │
│ - [3 条消息, 1200 tokens]                                  │
│                                                            │
└────────────────────────────────────────────────────────────┘
                             │
                             ▼
                      注入 Agent Prompt
```

---

## 4.4 记忆进化

### 4.4.1 自动摘要

```python
# backend/memory/evolution.py
class MemoryEvolution:
    """记忆进化 - 压缩、归档、遗忘"""

    def __init__(self, memory_manager: MemoryManager, llm_client):
        self.memory = memory_manager
        self.llm = llm_client

    async def daily_compression(self):
        """每日压缩 - 将工作记忆归档到情景记忆"""
        working = self.memory.working

        if len(working.messages) < 5:
            return

        # 生成摘要
        summary = await self._generate_summary(working.get_context())

        # 保存到情景记忆
        await self.memory.memorize(
            content=summary,
            memory_type="episodic",
            importance=5,
            metadata={"type": "daily_summary"}
        )

        # 清空工作记忆
        working.messages.clear()
        working.total_tokens = 0

    async def _generate_summary(self, messages: List[dict]) -> str:
        """使用 LLM 生成摘要"""
        prompt = f"""请总结以下对话的要点，生成一段简洁的摘要:

{chr(10).join([f"{m['role']}: {m['content']}" for m in messages])}

要求:
1. 提取关键信息和结论
2. 保留重要细节
3. 100字以内
"""

        response = await self.llm.complete(prompt)
        return response.strip()
```

### 4.4.2 重要性重评估

```python
async def reevaluate_importance(self):
    """定期重评估记忆重要性"""
    cursor = self.memory.db.cursor()

    # 获取低频访问的记忆
    cursor.execute("""
        SELECT * FROM memories_episodic
        WHERE access_count < 3
        AND importance > 1
        AND is_valid = 1
        AND created_at < ?
    """, [time.time() - 7 * 24 * 3600])  # 7 天前

    for row in cursor.fetchall():
        memory = dict(row)

        # 降低重要性
        new_importance = max(1, memory["importance"] - 1)

        cursor.execute("""
            UPDATE memories_episodic
            SET importance = ?
            WHERE id = ?
        """, [new_importance, memory["id"]])

    self.memory.db.commit()
```

### 4.4.3 遗忘机制

```python
async def prune_expired_memories(self):
    """清理过期记忆"""
    cursor = self.memory.db.cursor()

    # 删除过期记忆
    cursor.execute("""
        DELETE FROM memories_episodic
        WHERE expires_at IS NOT NULL
        AND expires_at < ?
    """, [time.time()])

    deleted = cursor.rowcount

    # 清理低价值记忆 (重要性极低 + 久未访问)
    cursor.execute("""
        DELETE FROM memories_episodic
        WHERE importance <= 1
        AND access_count = 0
        AND created_at < ?
    """, [time.time() - 30 * 24 * 3600])  # 30 天前

    deleted += cursor.rowcount
    self.memory.db.commit()

    logger.info(f"清理了 {deleted} 条过期记忆")
    return deleted
```

---

## 4.5 记忆 API

### 4.5.1 接口定义

```python
# backend/api/routes.py
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/memory", tags=["memory"])

class MemorySearchRequest(BaseModel):
    query: str
    memory_type: Optional[str] = None  # 'all' | 'episodic' | 'semantic'
    limit: int = 10

class MemorySaveRequest(BaseModel):
    content: str
    memory_type: str = "episodic"
    importance: int = 5
    tags: List[str] = []

@router.post("/search")
async def search_memory(req: MemorySearchRequest):
    """搜索记忆"""
    results = await memory_manager.remember(
        query=req.query,
        context={"memory_type_filter": req.memory_type}
    )
    return {"results": results}

@router.post("/save")
async def save_memory(req: MemorySaveRequest):
    """保存记忆"""
    await memory_manager.memorize(
        content=req.content,
        memory_type=req.memory_type,
        importance=req.importance,
        metadata={"tags": req.tags}
    )
    return {"success": True}

@router.get("/browser")
async def get_memory_browser(
    memory_type: str = "episodic",
    page: int = 1,
    page_size: int = 20
):
    """获取记忆浏览器数据"""
    # 实现分页查询
    ...
    return {"items": [], "total": 0, "page": page}
```

---

## 4.6 配置参数

### 4.6.1 记忆系统配置

```yaml
# backend/config.yaml
memory:
  working:
    max_tokens: 4000
    max_messages: 20
    eviction_policy: 'lru' # lru | importance

  episodic:
    enabled: true
    auto_save: true
    default_importance: 5
    ttl_days: null # null = 不过期
    retention:
      max_memories: 1000
      min_importance: 1

  semantic:
    enabled: true
    embedding_model: 'text-embedding-ada-002'
    dimension: 1536
    similarity_threshold: 0.7

  evolution:
    daily_summary_time: '02:00'
    compression_threshold: 50 # 消息数
    importance_decay_days: 30
```

---

## 4.7 Hermes Agent 参考实现

### 4.7.1 Hermes 记忆关键代码

```python
# Hermes agent/memory_manager.py (简化)
class MemoryManager:
    def __init__(self, provider=None):
        self.provider = provider or MemoryProvider()
        self.episodic = EpisodicMemory(self.provider)
        self.semantic = SemanticMemory(self.provider)

    async def retrieve(self, query: str, conversation_history: list) -> str:
        """Hermes 风格的记忆检索"""
        context_parts = []

        # 1. 语义记忆
        semantic = await self.semantic.search(query, limit=3)
        if semantic:
            context_parts.append("相关记忆:")
            context_parts.extend([s.content for s in semantic])

        # 2. 情景记忆 (当前会话)
        episodic = await self.episodic.get_current_session(conversation_history)
        if episodic:
            context_parts.append(f"当前会话: {episodic.summary}")

        return "\n".join(context_parts) if context_parts else ""
```

---

## 4.8 记忆作用域 (Scope 轴，P1 已落地)

三层记忆(Working/Episodic/Semantic)解决的是**时间轴**(短期→长期)；
scope 轴解决的是**归属**(这条记忆属于谁)。两者正交。

### 4.8.1 模型

`memories_episodic` / `memories_semantic` 各有两列:

| 列 | 取值 | 说明 |
|---|---|---|
| `scope` | `user` \| `project` \| `global` | 缺省 `user`(历史行迁移后同样落为 `user`) |
| `project_key` | 工作区绝对路径或 NULL | 与 `projects` 注册表 / `session_workspace_bindings.workspace_path` 同源，不引入新 ID |

三种作用域的语义(对齐 Claude Code / Cursor 的 user+project 规则分层):

- **user**: 关于用户本人的偏好与事实，跨项目可见(默认)。
- **project**: 只在绑定同一 `project_key` 的会话中可见，如项目约定、架构决策。
- **global**: 与具体项目无关的通用知识，任何会话可见。

### 4.8.2 写入:自动推导

存储层 `save()` 内统一调用 `backend/memory/scope.py::finalize_scope`，
覆盖所有写入口(manager / adapter / 固化晋升 / 抽取器):

- 显式传 `scope` → 尊重调用方；`project` 缺 key 时从会话的工作区绑定解析，
  解析不到(未绑定会话)降级为 `user`。
- 未传 → `derive_write_scope`:会话绑定了工作区 ⇒ 倾向 `project`，否则 `user`。
- 非 `project` 作用域强制 `project_key = NULL`。

进化管线中 episodic→semantic 的晋升会**继承**原行的 scope/project_key，
避免项目记忆晋升后泄漏为全局。

### 4.8.3 读取:可见性规则

```
可见 ⇔ scope != 'project'  或  行.project_key == 当前会话.project_key
```

- 自动注入链路(recall / get_context / 向量检索)**保持 session 严格隔离**
  (批次三 step 5 不变量)，scope 过滤是 adapter 融合后的兜底防线
  (`is_row_visible`)。
- 跨会话检索是显式 opt-in:`memory_search` 工具、`MemoryManager.search_memories`、
  `GET /memory/search` 均新增 `scope` 参数(`session|project|user|global`，
  默认 `session` 保持旧行为)；`memory_save` / `POST /memory/save` 接受
  `scope: auto|user|project|global`。
- `GET /memory/list` envelope 原样携带 `scope` / `project_key` 字段。

### 4.8.4 前端

`src/widgets/memory/MemoryBrowser.tsx`:每条记忆渲染作用域徽章
(用户/项目/全局，hover 显示 project_key 路径)，并提供"作用域"筛选行
(纯前端过滤，不改后端分页契约)。

### 4.8.5 后续路线(未实现)

- P2:项目画像进入 core 注入层(项目级 "MEMORY.md")。
- P3:Mem0 式冲突消解(ADD/UPDATE/DELETE/NOOP)+ `invalid_at` 时间有效区。
- P4:每周反思(reflection)与 recency×importance×confidence×relevance 四因子评分。

---

_文档版本: v1.1_
