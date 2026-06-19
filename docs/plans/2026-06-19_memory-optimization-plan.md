# Sage 记忆系统优化方案

> 日期: 2026-06-19
> 参考项目: Cherry Studio, Hermes Agent, Mem0, Letta (MemGPT), Zep
> 状态: 方案设计中

---

## 1. 现状评估

### 1.1 已有优势

Sage 的记忆系统架构骨架完整，采用三层人类记忆模型 + 六边形 Port/Adapter 模式：

| 组件 | 状态 | 说明 |
|------|------|------|
| 三层记忆模型 | ✅ 已实现 | Working / Episodic / Semantic |
| 六边形集成 | ✅ 已实现 | MemoryPort → MemoryAdapter → MemoryManager |
| ChatService 集成 | ✅ 已实现 | 检索 → 注入 → 存储 → 压缩四步 |
| 前端 UI | ✅ 已实现 | 记忆浏览器、新建、删除、导出 |
| 测试覆盖 | ✅ 较高 | 9 个测试文件 |

### 1.2 关键缺陷

| # | 缺陷 | 严重性 | 影响 |
|---|------|--------|------|
| 1 | **Working Memory 跨请求不持久** | 🔴 致命 | 每次请求重建 MemoryManager，工作记忆永远为空，压缩管道永不触发 |
| 2 | **无语义向量检索** | 🔴 严重 | 设计文档指定 ChromaDB + embedding，实际只有 FTS5 + LIKE，检索质量受限 |
| 3 | **FTS5 中文分词缺失** | 🟡 中等 | FTS5 默认 unicode61 分词器不支持中文，语义记忆搜索基本无效 |
| 4 | **记忆提取过于简单** | 🟡 中等 | 仅靠 6 个关键词检测偏好，importance 只有 5 和 7 两档 |
| 5 | **ConsolidationPipeline 未启用 LLM** | 🟡 中等 | MemoryAdapter 创建 ConsolidationPipeline 不传 llm_client，摘要都是 fallback |
| 6 | **记忆去重缺失** | 🟡 中等 | 每次对话都可能存储相同内容的记忆 |
| 7 | **Memory Tool 异步 bug** | 🟡 中等 | memory_tool.py 用 asyncio.new_event_loop() 包装异步调用 |
| 8 | **MemoryContext 固定条数** | 🟢 低 | 每层固定 3 条，不考虑 token 预算 |
| 9 | **MemoryManager 单例缺失** | 🟡 中等 | legacy_routes 和 evolution 系统每次新建实例 |

### 1.3 与业界差距

| 维度 | Sage 现状 | Cherry Studio | Hermes Agent | Mem0 | Letta |
|------|-----------|--------------|--------------|------|-------|
| 检索方式 | FTS5 + LIKE | 向量 + BM25 + RRF 混合 | FTS5 + 插件语义搜索 | 语义 + BM25 + 实体链接 | Agent 控制函数调用 |
| 记忆提取 | 关键词匹配 | LLM 事实抽取 | Agent 驱动手工整理 | LLM 门控 ADD/UPDATE/DELETE | Agent 自编辑 |
| 去重 | 无 | SHA-256 哈希去重 | 固定预算溢出触发 | 哈希去重 + 冲突解决 | Agent 决定 |
| Token 管理 | 固定 3 条/层 | 滑动窗口 + LLM 压缩 | 固定 ~1,300 token | ~7K token/对话 | Agent 自主管理 |
| 向量检索 | ❌ 无 | ✅ libsql 暴力扫描 | 插件提供 | ✅ 15+ 向量后端 | ✅ ChromaDB/pgvector |

---

## 2. 优化方案总览

### 2.1 设计原则（从参考项目提炼）

| 原则 | 来源 | 应用到 Sage |
|------|------|------------|
| **混合检索优于纯向量** | Cherry Studio (RRF), Mem0 (三路融合) | FTS5 + 向量 + 时间权重融合 |
| **写入时整合** | Mem0 (LLM 事实提取), Hermes (预算门控) | LLM 辅助事实提取 + 去重 |
| **分层注入** | Hermes (冻结快照), Letta (核心 vs 召回) | 核心记忆(始终可见) + 检索记忆(按需) |
| **Token 预算意识** | Hermes (固定预算), Anthropic (上下文腐烂) | 动态预算分配取代固定条数 |
| **异步非阻塞** | Cherry Studio (后台触发), Mem0 (异步模式) | 记忆提取/存储异步执行 |
| **时间感知** | Zep (双时间模型) | 记忆带有效期，支持事实变化 |

### 2.2 优化分 6 个阶段

```
阶段 1: 修复致命缺陷（Working Memory 持久化 + 单例）      → 1-2 天
阶段 2: 中文检索增强（jieba 分词 + FTS5 优化）             → 1 天
阶段 3: 向量检索（sqlite-vec + embedding）                 → 2-3 天
阶段 4: LLM 驱动的记忆提取与整合                           → 2-3 天
阶段 5: 混合检索 + Token 预算 + 注入优化                   → 2-3 天
阶段 6: 高级特性（时间感知 + 安全扫描 + 睡眠时计算）       → 3-5 天
```

---

## 3. 阶段 1：修复致命缺陷

### 3.1 MemoryManager 单例化

**问题**: `legacy_routes.py`、`main.py`、`evolution.py` 每次请求/任务都新建 MemoryManager，导致 Working Memory 永远为空。

**方案**: 在 `main.py` 中创建全局 MemoryManager 单例，通过 FastAPI 的依赖注入系统共享。

```python
# backend/main.py
_memory_manager: MemoryManager | None = None

def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager(...)
    return _memory_manager

# legacy_routes.py
@router.get("/memory/search")
async def search_memory(...):
    manager = get_memory_manager()  # 使用单例
    ...
```

**涉及文件**:
- `backend/main.py` — 添加单例工厂
- `backend/api/legacy_routes.py` — 使用单例
- `backend/scheduler/evolution.py` — 使用单例

### 3.2 Working Memory 持久化

**问题**: WorkingMemory 用纯内存 `collections.deque`，进程重启即丢失。

**方案**: 采用混合策略 — 进程内保持 deque（高性能），同时定期快照到 SQLite。

```python
# backend/memory/working.py
class WorkingMemory:
    def __init__(self, db_path: str, max_messages=20, max_tokens=4000):
        self._buffer = deque(maxlen=max_messages)
        self._db_path = db_path
        self._load_snapshot()  # 启动时恢复

    def _save_snapshot(self):
        """每次 add() 后异步写入 SQLite"""
        ...

    def _load_snapshot(self):
        """启动时从 SQLite 恢复最近 N 条"""
        ...
```

**涉及文件**: `backend/memory/working.py`

---

## 4. 阶段 2：中文检索增强

### 4.1 问题

FTS5 默认 `unicode61` 分词器按空白和标点分词，对中文无效。`"用户喜欢火锅"` 作为一个完整 token 存入 FTS5，搜索 `"喜欢"` 匹配不到。

### 4.2 方案：jieba 分词 + FTS5 自定义 tokenizer

```python
# backend/memory/chinese_tokenizer.py
import jieba

def chinese_tokenize(text: str) -> str:
    """将中文文本用 jieba 分词后，以空格连接供 FTS5 使用"""
    words = jieba.cut(text)
    return " ".join(words)
```

**改造 EpisodicMemory**:
- 存储时对 content 做 jieba 分词，结果存入专用 FTS5 列
- 搜索时也对 query 做 jieba 分词

**改造 SemanticMemory**:
- FTS5 虚拟表使用分词后的文本

**涉及文件**:
- 新建 `backend/memory/chinese_tokenizer.py`
- 修改 `backend/memory/episodic.py`
- 修改 `backend/memory/semantic.py`
- 修改 `backend/data/database.py`（FTS5 表结构）

---

## 5. 阶段 3：向量检索

### 5.1 技术选型

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| **sqlite-vec** | 纯 SQLite 扩展，零额外依赖，与现有 SQLite 完美融合 | 无 ANN 索引（暴力扫描），适合 <100K 向量 | ✅ 首选 |
| ChromaDB | 零配置，嵌入式 | 额外进程/依赖，内存占用大 | 备选 |
| Qdrant | 生产级，功能全 | 需 Docker，对桌面应用太重 | ❌ |
| pgvector | 已用 PostgreSQL 时最佳 | Sage 用 SQLite，引入 PG 太重 | ❌ |

**选择: sqlite-vec** — Sage 已全栈 SQLite，sqlite-vec 是 SQLite 的向量扩展，零额外依赖，暴力扫描对桌面应用场景足够。

### 5.2 架构设计

```
                  ┌─────────────────────┐
                  │   Embedding Model   │
                  │  (本地/API 可选)     │
                  └──────────┬──────────┘
                             │ 向量
┌────────────┐    ┌──────────▼──────────┐    ┌────────────────┐
│  记忆存储   │───▶│   sqlite-vec 表     │    │  MemoryPort    │
│ (SQLite)   │    │  memories_vec        │◀───│  retrieve()    │
│            │    │  (embedding BLOB)    │    │  → 混合检索     │
└────────────┘    └─────────────────────┘    └────────────────┘
```

### 5.3 Embedding 模型选择

| 模型 | 维度 | 来源 | 成本 | 推荐 |
|------|------|------|------|------|
| `text-embedding-3-small` | 1536 | OpenAI API | $0.02/1M tokens | ✅ API 首选 |
| `bge-m3` / `bge-small-zh` | 512-1024 | BAAI (本地) | 免费 | ✅ 本地首选 |
| `nomic-embed-text` | 768 | Nomic (本地) | 免费 | ✅ Ollama 本地 |

**策略**: 优先使用本地模型（隐私 + 免费），可配置切换为 API。

### 5.4 存储层改造

```python
# backend/memory/vector_store.py
import sqlite_vec
from scipy.spatial.distance import cosine

class VectorStore:
    """基于 sqlite-vec 的向量存储"""

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)

        # 创建向量虚拟表
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec USING vec0(
                embedding FLOAT[512],
                memory_id TEXT,
                memory_type TEXT
            )
        """)

    def add(self, memory_id: str, text: str, embedding: list[float], memory_type: str):
        ...

    def search(self, query_embedding: list[float], top_k: int = 10,
               memory_type: str | None = None) -> list[dict]:
        """余弦距离搜索"""
        ...
```

### 5.5 MemoryAdapter 改造

```python
# backend/adapters/out/memory/adapter.py
class MemoryAdapter(MemoryPort):
    def retrieve(self, query: str, session_id: str, limit: int = 5) -> MemoryContext:
        # 1. 向量检索（语义相似度）
        query_embedding = self._embedder.encode(query)
        vector_results = self._vector_store.search(query_embedding, top_k=limit * 3)

        # 2. FTS5 检索（关键词）
        fts_results = self._semantic.search_fts(query, limit=limit * 2)

        # 3. 混合融合（RRF）
        merged = self._reciprocal_rank_fusion(vector_results, fts_results)

        return MemoryContext(
            working=self._working.get_recent(limit),
            episodic=self._episodic.search(query, limit),
            semantic=merged[:limit]
        )
```

### 5.6 涉及文件

| 文件 | 变更 |
|------|------|
| 新建 `backend/memory/vector_store.py` | sqlite-vec 向量存储 |
| 新建 `backend/memory/embedder.py` | Embedding 模型封装（本地/API） |
| 修改 `backend/adapters/out/memory/adapter.py` | 接入向量检索 |
| 修改 `backend/memory/manager.py` | 集成 VectorStore |
| 修改 `backend/data/database.py` | 添加 sqlite-vec 扩展初始化 |
| 修改 `backend/requirements.txt` | 添加 `sqlite-vec`, `sentence-transformers` |
| 修改 `config.yaml` | 添加 embedding 配置节 |

---

## 6. 阶段 4：LLM 驱动的记忆提取与整合

### 6.1 借鉴 Mem0 的事实提取

当前 Sage 的 `_extract_and_store_memory()` 仅靠 6 个关键词匹配，过于简陋。改为 LLM 驱动的原子事实提取：

```python
# backend/memory/extractor.py
EXTRACTION_PROMPT = """从以下对话中提取关键事实。每个事实应该是独立的、原子化的陈述。
如果事实已经存在于已知事实中，跳过。
如果有矛盾，以最新信息为准。

已知事实:
{existing_facts}

对话内容:
[用户]: {user_message}
[助手]: {assistant_message}

以 JSON 数组格式输出提取的事实，每个事实包含:
- content: 事实内容（一句话）
- importance: 1-10 的重要性评分
- category: preference/fact/event/intent
- tags: 相关标签列表

如果没有值得提取的事实，返回空数组 []。"""

class MemoryExtractor:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def extract(self, user_msg: str, assistant_msg: str,
                      existing_facts: list[str]) -> list[dict]:
        prompt = EXTRACTION_PROMPT.format(
            existing_facts="\n".join(existing_facts[:20]),
            user_message=user_msg[:500],
            assistant_message=assistant_msg[:500]
        )
        response = await self.llm.chat([{"role": "user", "content": prompt}])
        return json.loads(response)  # 返回 [{"content": ..., "importance": ..., ...}]
```

### 6.2 借鉴 Mem0 的去重与冲突解决

```python
class MemoryConsolidator:
    """写入时整合 — 去重 + 冲突解决"""

    async def consolidate(self, new_facts: list[dict],
                          existing_memories: list[dict]) -> list[dict]:
        """
        对每个新事实，决定操作:
        - ADD: 全新事实
        - UPDATE: 更新现有记忆（更丰富的信息）
        - DELETE: 移除被矛盾的记忆
        - NOOP: 已存在或不相关
        """
        actions = []
        for fact in new_facts:
            # 检索语义相似的现有记忆
            similar = self._vector_store.search(
                self._embedder.encode(fact["content"]), top_k=5
            )

            if not similar or similar[0]["score"] < 0.85:
                actions.append({"op": "ADD", "fact": fact})
            else:
                # LLM 判断是更新、删除还是跳过
                action = await self._llm_decide(fact, similar)
                actions.append(action)

        return actions
```

### 6.3 ConsolidationPipeline 启用 LLM

```python
# 当前: ConsolidationPipeline() 不传 llm_client
# 改为:
class MemoryAdapter(MemoryPort):
    def __init__(self, llm_client: LLMClient = None, ...):
        self._consolidation = ConsolidationPipeline(llm_client=llm_client)
```

### 6.4 涉及文件

| 文件 | 变更 |
|------|------|
| 新建 `backend/memory/extractor.py` | LLM 事实提取器 |
| 新建 `backend/memory/consolidator.py` | 去重 + 冲突解决 |
| 修改 `backend/adapters/out/memory/adapter.py` | 接入 LLM 提取和整合 |
| 修改 `backend/application/services/chat_service.py` | 替换 `_extract_and_store_memory()` |
| 修改 `config.yaml` | 添加 memory.extraction 配置 |

---

## 7. 阶段 5：混合检索 + Token 预算 + 注入优化

### 7.1 借鉴 Cherry Studio 的 RRF 混合检索

```python
def reciprocal_rank_fusion(
    results_list: list[list[dict]],
    k: int = 60,
    alpha: float = 0.6  # 向量权重
) -> list[dict]:
    """
    RRF: score = α / (k + rank_vector) + (1-α) / (k + rank_bm25)
    Cherry Studio 默认 hybridAlpha=0.6, K=60
    """
    scores = {}
    for results, weight in zip(results_list, [alpha, 1 - alpha]):
        for rank, item in enumerate(results):
            id = item["id"]
            if id not in scores:
                scores[id] = {"item": item, "score": 0}
            scores[id]["score"] += weight / (k + rank + 1)

    return sorted(scores.values(), key=lambda x: x["score"], reverse=True)
```

### 7.2 借鉴 Hermes 的 Token 预算管理

```python
# backend/domain/memory.py
@dataclass
class MemoryContext:
    # 改为 Token 预算感知
    core: list[dict]       # 核心记忆（始终注入，类似 Hermes 的 MEMORY.md）
    episodic: list[dict]   # 情景记忆（按需检索）
    semantic: list[dict]   # 语义记忆（按需检索）

    def format(self, budget_tokens: int = 1500) -> str:
        """
        分层注入，借鉴 Hermes 的三层系统提示:
        - 稳定层: 核心记忆（用户画像 + 偏好），始终在 system prompt
        - 易变层: 检索到的情景/语义记忆，按 token 预算截断
        """
        parts = []

        # 核心记忆 — 始终注入（~500 token）
        if self.core:
            core_text = "\n".join(f"- {m['content']}" for m in self.core)
            parts.append(f"【用户画像】\n{core_text}")

        # 情景 + 语义记忆 — 按预算分配剩余空间
        remaining_budget = budget_tokens - self._estimate_tokens(parts[0] if parts else "")
        memory_items = self.episodic + self.semantic
        memory_items.sort(key=lambda m: m.get("importance", 5), reverse=True)

        memory_text = ""
        for item in memory_items:
            item_text = f"- {item['content']}"
            item_tokens = self._estimate_tokens(item_text)
            if item_tokens > remaining_budget:
                break
            memory_text += item_text + "\n"
            remaining_budget -= item_tokens

        if memory_text:
            parts.append(f"【相关记忆】\n{memory_text}")

        return "\n\n".join(parts)
```

### 7.3 借鉴 Hermes 的冻结快照

```python
# backend/application/services/chat_service.py
class ChatService:
    async def _run_turn_inner(self, ...):
        # 会话开始时获取记忆快照，之后冻结
        if not hasattr(self, '_memory_snapshot') or self._memory_snapshot is None:
            self._memory_snapshot = await self._build_memory_snapshot(session_id)

        # 注入冻结快照到 system prompt（保护 KV Cache）
        system_content += self._memory_snapshot.format()
```

### 7.4 涉及文件

| 文件 | 变更 |
|------|------|
| 新建 `backend/memory/fusion.py` | RRF 混合融合 |
| 修改 `backend/domain/memory.py` | Token 预算感知的 format() |
| 修改 `backend/application/services/chat_service.py` | 冻结快照 + 预算注入 |

---

## 8. 阶段 6：高级特性

### 8.1 时间感知（借鉴 Zep）

为记忆添加时间有效期，支持事实变化：

```python
# backend/domain/memory.py
@dataclass
class MemoryItem:
    id: str
    content: str
    valid_at: int        # 事实在真实世界中何时为真
    created_at: int      # 系统何时记录
    superseded_at: int | None = None  # 被取代时间（非删除）
    ...
```

### 8.2 安全扫描（借鉴 Hermes）

记忆写入前进行安全检查：

```python
# backend/memory/safety.py
class MemorySafetyScanner:
    """三级威胁扫描"""

    def scan_write(self, content: str) -> ScanResult:
        """写入前扫描"""
        # Level 1: 经典注入检测
        if self._detect_injection(content):
            return ScanResult(blocked=True, reason="疑似 prompt 注入")

        # Level 2: 数据泄露检测
        if self._detect_data_leak(content):
            return ScanResult(blocked=True, reason="疑似数据泄露")

        # Level 3: 持久化攻击检测
        if self._detect_persistence_attack(content):
            return ScanResult(blocked=True, reason="疑似持久化攻击")

        return ScanResult(blocked=False)
```

### 8.3 睡眠时计算（借鉴 Letta）

利用 evolution 系统中的定时任务，异步整合记忆：

```python
# backend/scheduler/evolution.py — 增强 MemoryPruning
class MemoryDreamJob:
    """
    定期（每周日凌晨）运行:
    1. 检索近期所有情景记忆
    2. 用 LLM 提取高频事实 → 提升为语义记忆
    3. 合并重复的语义记忆
    4. 降低长期未访问记忆的重要性
    5. 清理 superseded 记忆
    """
```

---

## 9. 完整架构图

```
┌────────────────────────────────────────────────────────────────────────┐
│                           前端 (React/TypeScript)                       │
│  MemoryBrowser → 记忆浏览/筛选/统计                                     │
│  NewMemoryModal → 手动新建记忆                                          │
│  记忆搜索/删除/导出                                                     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Tauri IPC / HTTP
┌──────────────────────────────────▼─────────────────────────────────────┐
│                         API 层 (FastAPI)                                │
│  legacy_routes.py: /memory/search|save|delete|list                     │
│  hex_routes.py: ChatService 通过 MemoryPort 间接使用                    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                   Application 层 (ChatService)                          │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Chat Turn 流程                                │   │
│  │                                                                  │   │
│  │  Step 1: 持久化 user message                                    │   │
│  │  Step 1.5: 混合检索记忆 (向量 + FTS5 + RRF)                     │   │
│  │  Step 2: 拉取历史上下文                                         │   │
│  │  Step 2.5: 注入记忆（Token 预算感知 + 冻结快照）                 │   │
│  │  Step 3: 调用 LLM                                              │   │
│  │  Step 4: 执行 tool_calls                                       │   │
│  │  Step 5: 持久化 assistant response                              │   │
│  │  Step 6: 安全扫描 + LLM 事实提取 + 去重整合                     │   │
│  │  Step 7: 异步存储新记忆（不阻塞响应）                            │   │
│  │  Step 8: 压缩工作记忆 → 摘要存 episodic                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ MemoryPort (Protocol)
┌──────────────────────────────────▼─────────────────────────────────────┐
│                    Port 层 (MemoryPort)                                 │
│  retrieve(query, session_id, limit) → MemoryContext                    │
│  store(content, session_id, importance, tags) → str                    │
│  compress(session_id) → None                                           │
│  consolidate() → None  (新增: 定期整合)                                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                    Adapter 层 (MemoryAdapter)                           │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │   Working    │  │   Episodic   │  │   Semantic   │  │  Vector   │  │
│  │   Memory     │  │   Memory     │  │   Memory     │  │  Store    │  │
│  │  (deque +    │  │  (SQLite +   │  │  (SQLite +   │  │(sqlite-vec│  │
│  │   SQLite     │  │   FTS5 +     │  │   FTS5 +     │  │           │  │
│  │   snapshot)  │  │   jieba)     │  │   jieba)     │  │           │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘  │
│         │                 │                  │                │         │
│  ┌──────▼─────────────────▼──────────────────▼────────────────▼─────┐  │
│  │                    共享服务层                                      │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐  │  │
│  │  │ Extractor  │  │Consolidator│  │  Embedder  │  │  Safety   │  │  │
│  │  │ (LLM 事实  │  │ (去重 +    │  │ (本地/API  │  │  Scanner  │  │  │
│  │  │  提取)     │  │  冲突解决) │  │  向量化)   │  │ (安全扫描) │  │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └───────────┘  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                    数据持久化层 (SQLite)                                 │
│                                                                         │
│  memories_episodic      — FTS5 全文索引 + jieba 分词                   │
│  memories_semantic      — FTS5 全文索引 + jieba 分词                   │
│  memories_vec           — sqlite-vec 向量索引                          │
│  memories_evolution_log — 记忆进化日志                                 │
│  working_memory_snapshot— 工作记忆快照                                 │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 10. 技术选型总结

| 组件 | 选择 | 理由 |
|------|------|------|
| 向量 DB | **sqlite-vec** | 零额外依赖，与现有 SQLite 完美融合，暴力扫描对桌面应用足够 |
| 嵌入模型 | **BGE-M3 (本地) / text-embedding-3-small (API)** | 本地免费 + API 可选 |
| 中文分词 | **jieba** | 成熟稳定，Python 生态标准 |
| 混合检索 | **RRF (K=60, alpha=0.6)** | Cherry Studio 验证，实现简单 |
| 事实提取 | **LLM 驱动 (Mem0 模式)** | 远优于关键词匹配 |
| 去重 | **向量相似度 + LLM 判断** | ADD/UPDATE/DELETE/NOOP 四操作 |
| Token 管理 | **分层预算 + 动态截断** | 取代固定条数 |
| 安全 | **三级扫描 (Hermes 模式)** | 写入前 + 加载前 |

---

## 11. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| sqlite-vec 编译兼容性问题 | 中 | 高 | 提供纯 Python fallback (numpy 余弦) |
| jieba 分词性能 | 低 | 中 | 首次加载词典需约 1s，后续 O(1) |
| LLM 事实提取增加延迟 | 中 | 中 | 异步执行，不阻塞响应 |
| Embedding 模型体积 | 中 | 低 | BGE-M3 约 400MB，可接受 |
| 向量检索精度不如预期 | 低 | 中 | RRF 混合检索兜底 |

---

## 12. 实施步骤（详细 TODO）

### 阶段 1: 修复致命缺陷（1-2 天）
- [x] 1.1 MemoryManager 单例化
- [x] 1.2 Working Memory SQLite 快照持久化
- [x] 1.3 单元测试验证 Working Memory 跨请求持久

### 阶段 2: 中文检索增强（1 天）
- [x] 2.1 实现 jieba 中文分词模块
- [x] 2.2 改造 EpisodicMemory 使用分词后文本
- [x] 2.3 改造 SemanticMemory FTS5 使用分词后文本
- [x] 2.4 迁移脚本：不需要 — 最终方案使用 LIKE + jieba 查询侧分词，现有数据无需迁移
- [x] 2.5 中文检索测试用例

### 阶段 3: 向量检索（2-3 天）
- [ ] 3.1 实现 Embedder 封装（本地 BGE-M3 + API 可选）
- [ ] 3.2 实现 VectorStore（sqlite-vec）
- [ ] 3.3 MemoryAdapter 接入向量检索
- [ ] 3.4 记忆存储时自动生成 embedding
- [ ] 3.5 迁移脚本：为现有记忆生成 embedding
- [ ] 3.6 向量检索测试

### 阶段 4: LLM 驱动的记忆提取（2-3 天）
- [ ] 4.1 实现 MemoryExtractor（LLM 事实提取）
- [ ] 4.2 实现 MemoryConsolidator（去重 + 冲突解决）
- [ ] 4.3 ConsolidationPipeline 接入 LLM
- [ ] 4.4 ChatService 替换 _extract_and_store_memory()
- [ ] 4.5 集成测试

### 阶段 5: 混合检索 + Token 预算（2-3 天）
- [ ] 5.1 实现 RRF 混合融合
- [ ] 5.2 MemoryContext.format() Token 预算感知
- [ ] 5.3 核心记忆层（用户画像 + 偏好）
- [ ] 5.4 冻结快照机制
- [ ] 5.5 端到端集成测试

### 阶段 6: 高级特性（3-5 天）
- [ ] 6.1 时间感知（valid_at + superseded_at）
- [ ] 6.2 安全扫描（写入前 + 加载前）
- [ ] 6.3 睡眠时计算（MemoryDreamJob）
- [ ] 6.4 前端 UI 增强（时间线视图、安全标记）

---

## 13. 参考来源

- [Cherry Studio GitHub](https://github.com/CherryHQ/cherry-studio) — 知识库架构、RRF 混合搜索
- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — 固定预算、冻结快照、安全扫描
- [Mem0 论文 (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413) — LLM 事实提取、ADD/UPDATE/DELETE/NOOP
- [Letta/MemGPT (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560) — OS 虚拟内存类比、Agent 自管理
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — SQLite 向量扩展
- [Hindsight/Vectorize](https://hindsight.vectorize.io/blog/2026/05/21/agent-memory-consolidation) — 四杠杆整合框架
- [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — 上下文设计最佳实践
