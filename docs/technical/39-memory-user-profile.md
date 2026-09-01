# 39 — 记忆系统与用户画像（Memory / UserProfile）

> 本文档描述 sage 的记忆系统架构与 2026-08-02 新增的**用户画像（USER.md 概念）**沉淀。
> 技能使用跟踪见 [24-skills-system.md §10.11](./24-skills-system.md)。

## 1. 三层记忆架构

记忆系统分三层（`backend/memory/`）：

| 层 | 实现 | 存储 | 特点 |
|----|------|------|------|
| Working | `working.py` | 内存 deque + SQLite 快照 | 滑动窗口，按 `session_id` 隔离，`max_size=20` / `max_tokens=4000` |
| Episodic | `episodic.py` | SQLite `memories_episodic` | 情景记忆，jieba 分词 LIKE 搜索，软删除 |
| Semantic | `semantic.py` | SQLite `memories_semantic` + FTS5 | 语义记忆，独立 FTS5 虚拟表（jieba 分词），Python 侧显式同步索引 |

`MemoryManager`（`backend/memory/manager.py`）统一管理三层：`memorize` / `recall` /
`get_context` / `compress` / `search_memories` / `delete_memory`。分类规则集中在
模块级 `classify_memory_type`（importance ≥ 8 → semantic；短内容且 importance < 5 → working；其余 → episodic）。

`MemoryAdapter`（`backend/adapters/out/memory/adapter.py`）桥接 `MemoryPort` 协议：
`store()` 自动生成 embedding 入 VectorStore（sqlite-vec），`retrieve()` 用 **RRF 融合**
（关键词 0.4 + 向量 0.6）多路检索。

## 2. 用户画像（USER.md 概念, 2026-08-02 PR #269）

借鉴 hermes-agent 的 `USER.md` frozen snapshot 模式：把"关于用户的知识"
（偏好 / 沟通风格 / 工作习惯 / 身份 / 目标）与通用记忆分离，以**冻结快照**方式
始终注入 system prompt（不依赖每轮检索命中）。

### 2.1 UserProfileStore（`backend/memory/user_profile.py`）

持久画像库，SQLite `user_profile` 表：

```sql
CREATE TABLE user_profile (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'preference',   -- preference/communication_style/workflow_habit/identity/goal
    importance INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
    created_at INTEGER NOT NULL,                    -- ms epoch
    updated_at INTEGER
);
```

设计要点：

- **冻结快照**：`load()` 时从 DB 读取并计算 `_snapshot_entries` + `_snapshot`；
  `add()` 只更新 DB，**不刷新快照**（保 prefix cache）。显式 `invalidate()` 才刷新。
- **字符上限**：快照按重要性降序截断到 `DEFAULT_CHAR_LIMIT = 1400`。
- **去重**：完全一致 / 子串包含 / `SequenceMatcher` 相似度 ≥ 0.95 视为重复，拒绝写入。
- **安全**：写入前 `get_scanner().scan_write()`（Hermes 风格三级威胁扫描）。
- **importance 钳制**：`add()` 钳制到 1-10（防 DB CHECK 越界抛 IntegrityError）。
- 全局单例 `get_user_profile()` / `reset_user_profile()`。

### 2.2 分类路由（`extract_and_store_memory`）

记忆写入统一走 `chat_service.extract_and_store_memory`（hex ChatService 与 legacy
`/chat/stream` 共用）。按 extractor 产出的 `category` 分流：

- `preference` / `goal` → `memory_port.store_profile()`（画像库）
- `fact` / `event` 及其余 → `memory_port.store()`（通用三层记忆）

结构探测用**类级** `hasattr(type(memory_port), "store_profile")`（非实例 getattr），
避免无 spec 的 MagicMock 误判为"已实现"。`store_profile()` 在画像库不可用时
**降级到 `store()`**——偏好事实不因画像库故障而丢失。

### 2.3 双路径注入

画像快照经两条路径注入，保证 legacy（当前生效）与 hex 都能拿到同一份用户知识：

| 路径 | 注入点 | 快照来源 |
|------|--------|----------|
| legacy | `MemoryManager.get_context()` 前置 `## USER PROFILE` 块 | `get_snapshot()`（冻结 + char 受限） |
| hex | `MemoryAdapter.retrieve()` → `MemoryContext.core` | `get_core_items()`（基于 `_snapshot_entries`，同源） |

### 2.4 core 独立预算

`retrieve()` 的 `core` 槽位按**画像 / 检索命中独立预算**（画像 3 + 检索 2 = 5），
防止画像条目挤掉本轮检索到的高重要性（importance ≥ 8）事实：

```python
_CORE_PROFILE_LIMIT = 3
_CORE_RETRIEVED_LIMIT = 2
core = core_profile[:_CORE_PROFILE_LIMIT] + core_retrieved[:_CORE_RETRIEVED_LIMIT]
```

## 3. 相关文件

- 新增：`backend/memory/user_profile.py`、`backend/tests/unit/test_user_profile.py`
- 修改：`backend/adapters/out/memory/adapter.py`（`store_profile` + core 预算）、
  `backend/memory/manager.py`（`get_context` 前置画像）、
  `backend/application/services/chat_service.py`（分类路由）、
  `backend/data/database.py`（新表 `user_profile`）
- 新表：`user_profile`（幂等建表）

## 4. Background Review 自主进化系统（2026-08-03 实施）

系统自动检测"值得提炼为技能"的对话模式，异步生成技能草稿，等待用户审批。

### 4.1 信号检测

`backend/skills/pattern_detector.py` — 四种触发源：

| 信号 | 触发条件 | 阈值 |
|------|----------|------|
| 复杂对话轮次 | 单轮 tool_calls 数量 ≥ N | `COMPLEX_TURN_THRESHOLD = 5` |
| 低成功率技能 | 某技能失败率超过阈值 | `FAIL_RATE_THRESHOLD = 0.5`（至少 3 次调用） |
| 重复模式 | 相同 tool 组合在窗口内反复出现 | `REPEAT_THRESHOLD = 3` 次/窗口 |
| /learn 命令 | 用户显式触发 | 任意时刻 |

`ChatService` 在每轮响应后调用 `record_signal()`，信号写入 `review_events` 表。

### 4.2 异步审查队列

`backend/skills/review_queue.py` — 后台单线程 worker + SQLite 持久化：

- `enqueue(event)` 写入 `review_events` 表
- Worker 每 `POLL_INTERVAL_S=5` 秒取一批未处理事件（FIFO + `id` 升序去重）
- 成组交给 `ReviewService.generate_draft()` 生成技能草稿
- 处理完标记 `processed_at`；进程退出时 `drain()` 安全排空

### 4.3 LLM 驱动的技能草稿生成

`backend/skills/review_service.py`：

- 从 `review_events` + `skill_usage` + `working_memory` 聚合上下文
- 调用 LLM（prompt 模板 `backend/skills/prompts/review.txt`）生成 SKILL.md 草稿
- 草稿写入 `skill_drafts` 表（`SkillDraftStore`，CRUD 封装）

### 4.4 审批队列

- **API**: `POST /learn`（用户显式触发）、`GET /skill-drafts`（列出草稿）、
  `POST /skill-drafts/:id/approve`、`POST /skill-drafts/:id/reject`
- **前端**: Skills 页面新增 "Pending Drafts" 标签页（`SkillDraftList.tsx`），
  轮询草稿列表，Approve/Reject 按钮
- **ChatInput**: `/learn` 斜杠命令（`slashCommands.ts` + `Chat.tsx` handleLearn）

### 4.5 数据库 schema

`backend/data/database.py` 新增两张表（幂等建表）：

```sql
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload TEXT,
    processed_at INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_drafts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_events TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    reviewed_at INTEGER
);
```

### 4.6 相关文件

| 文件 | 职责 |
|------|------|
| `backend/skills/pattern_detector.py` | 信号检测（复杂轮次/重复模式/失败率） |
| `backend/skills/review_queue.py` | 异步队列 + SQLite 持久化 + worker |
| `backend/skills/review_service.py` | LLM 调用 + 上下文聚合 + 草稿生成 |
| `backend/skills/draft_store.py` | skill_drafts 表 CRUD |
| `backend/skills/prompts/review.txt` | LLM prompt 模板 |
| `backend/skills/usage.py` | `fail_count` 列（成功率跟踪） |
| `backend/api/legacy_routes.py` | /learn + /skill-drafts API |
| `src/widgets/skills/SkillDraftList.tsx` | Pending Drafts UI 组件 |
| `src/widgets/chat/ChatInput.tsx` | /learn 斜杠命令 |
| `src/pages/Chat.tsx` | handleLearn IPC 调用 |
| `electron/commands.ts` | trigger_learn IPC handler |

## 5. 后续工作（未实施）

- 记忆提取异步化（legacy 已非阻塞，hex 收益有限，留待 API_MODE=hex 启用后）
- Skill curator 生命周期（active/stale/archived）
