# Storage Adapter asyncio.to_thread — Design Spec

- **Date:** 2026-08-10
- **Branch:** `feat/storage-asyncio-to-thread` (基于 `origin/main`)
- **Status:** Draft, 待用户 review
- **Author:** Claude (brainstorming with user)
- **Ref:** `docs/plans/2026-08-09_feature-optimization-proposal.md` §1.2 PR B

## 1. 背景与目标

### 1.1 问题

PR #294 §1.2（PR A）把 34 个无 `await` 的 `async def` handler 降级为 `def`，让 FastAPI/Starlette 把它们 dispatch 到 anyio 默认 threadpool，事件循环不再被 SQLite 同步写阻塞。回归测试 `test_event_loop_blocking.py` 守住这条路径。

但 PR A 只覆盖了一条入口：`backend/api/legacy_routes.py` 直接走 `Depends(get_session_repo)` 的 handler。Sage 的另一条持久化入口——**通过 `chat_service` / `session_service` → `StorageAdapter`** ——**完全没有被 PR A 触及**。

具体阻塞点（已确认）：

| 文件 | 行 | 调用 |
|---|---|---|
| `backend/application/services/chat_service.py` | 155 | `session_id = await self.storage.create_session(title=title)` |
| 同上 | 173 | `await self.storage.delete_session(session_id)` |
| 同上 | 238 | `await self.storage.append_message(session_id, user_message)` |
| 同上 | 259 | `history = await self.storage.get_messages(...)` |
| 同上 | 448 | `await self.storage.append_message(session_id, response)` |
| 同上 | 510 | `session_data = await self.storage.get_session(session_id)` |
| 同上 | 518 | `await self.storage.update_session(session_id, title=title)` |
| 同上 | 737 | `await self.storage.append_message(session_id, tool_message)` |
| `backend/application/services/session_service.py` | 98, 120, 125, 148, 160, 161, 174, 196 | 8 处 `await self.storage.X(...)` |

这些 `await` 调用链最终落到 `SqliteStorageAdapter`：

```python
# 当前实现（PR B 之前）
async def create_session(self, title: str = "") -> str:
    safe_title = title if title else _DEFAULT_TITLE
    session = self._sessions.create(title=safe_title)  # ← 同步 SQLite 调用
    return str(session.id)
```

`async def` 但**内部无 await**，实际是同步阻塞。当 chat handler（`async def`, keep_async from PR A）在事件循环上 `await self.storage.create_session(...)`，同步 SQLite 写**直接在事件循环线程上执行**，阻塞期间 SSE 推送、`/health` 响应、其他 handler 调度全部排队等待。

`SqliteStorageAdapter` 的 docstring 已经明确这个反模式：

> 直接调用同步方法而不额外套 `asyncio.to_thread`：FastAPI handler 已经处于事件循环,SQLite 同步调用在线程内非阻塞且不耗 IO 等待

但这个假设**只对 PR A 已降级的 `def` handler 成立**——handler 跑在 threadpool 内。对 `chat_service` / `session_service` 这条路径**完全不成立**：chat handler 是 `async def` keep_async，在事件循环上跑。

### 1.2 目标

把 `SqliteStorageAdapter` + `MemoryStorageAdapter` 的所有 async 方法改为 `asyncio.to_thread` 包装，让同步实现 offload 到 anyio threadpool，事件循环只在微秒级 Python 字节码上跑：

1. **SqliteStorageAdapter 7 个方法**全部 `async → 异步包装(_sync_X)`，包装内 `async with self._lock: await asyncio.to_thread(self._sync_X, ...)`
2. **MemoryStorageAdapter 7 个方法**全部同样改写，但**无锁**（纯内存，无并发问题）
3. **接口零变化**：`StoragePort` protocol、调用方（`chat_service` / `session_service` / `main.py` DI）、底层 `SessionRepository` / `MessageRepository` 全部不动
4. **回归保护**：单元测试验证 to_thread 调用点 + 实际线程身份 + 锁串行化；集成测试沿用 PR A 的 `/health` 探针模式，加 chat_stream 场景

### 1.3 非目标 (YAGNI)

- 不改 `StoragePort` 接口签名（保持 async,调用者无感）
- 不改 `chat_service` / `session_service`（它们只是 await adapter,改 adapter 它们自动受益）
- 不改 `SessionRepository` / `MessageRepository` 底层（保持同步,to_thread 内部直接调）
- 不引入新锁原语 —— 统一到单一 module-level `threading.Lock`,放在 `backend/data/database.py` 模块级 `_SQLITE_LOCK`,adapter 与 handler 共享同一把
- 不引入异步 SQLite 驱动（如 aiosqlite）——保持同步 driver + threadpool offload 模式
- 不做 connection pool —— 单例 `SessionRepository` + 模块级锁已正确
- 改 PR A 的 `_db_lock` 共享方式：让 `legacy_routes.py` 改 import `backend.data.database._SQLITE_LOCK as _db_lock`,两条路径在同一把锁上互斥,避免同连接事务竞争

## 2. 用户故事

- **US-1**：作为开发，chat 主链路在 50 并发 `chat_stream_create` 时，`/health` P99 应 < 100ms（修复前 > 200ms）
- **US-2**：作为维护者，我希望 SqliteStorageAdapter 的所有 SQLite 写都在 threadpool 跑，事件循环空闲，便于 SSE 流畅推送
- **US-3**：作为单测作者，我希望 MemoryStorageAdapter 仍能用作单测替身（保持 in-process dict 语义），同时接口签名一致（也是 async def）
- **US-4**：作为 reviewer，我希望 adapter 改动保持最小且局部，PR diff 集中、不污染 chat_service / session_service

## 3. 架构

### 3.1 数据流

```
                  ┌──────────────────────────────────────────────────────┐
                  │ FastAPI event loop (主线程)                           │
                  │   chat handler (async def, keep_async from PR A)    │
                  │     └─→ chat_service.create_session()              │
                  │           └─→ await storage.create_session()       │
                  │                 │                                  │
                  │                 ▼ (进 threadpool via to_thread)   │
                  ├──────────────────────────────────────────────────────┤
                  │ anyio default threadpool (40 worker threads)        │
                  │   ┌────────────────────────────────────────────┐    │
                  │   │ SqliteStorageAdapter._sync_create_session()│    │
                  │   │   ├─ self._lock (asyncio.Lock)             │    │
                  │   │   └─ SessionRepository.create() [blocking] │    │
                  │   └────────────────────────────────────────────┘    │
                  │                                                      │
                  │ MemoryStorageAdapter 同结构,但无 self._lock          │
                  └──────────────────────────────────────────────────────┘
```

### 3.2 SqliteStorageAdapter 改写模板

```python
class SqliteStorageAdapter:
    def __init__(
        self,
        session_repo: Optional[SessionRepository] = None,
        message_repo: Optional[MessageRepository] = None,
    ) -> None:
        self._sessions: SessionRepository = session_repo or SessionRepository()
        self._messages: MessageRepository = message_repo or MessageRepository()
        self._lock = asyncio.Lock()  # 实例级锁,保护并发 SQLite 单例连接(adapter 是 async def,async with 需 async-native lock)
    
    async def create_session(self, title: str = "") -> str:
        async with self._lock:
            return await asyncio.to_thread(self._sync_create_session, title)
    
    def _sync_create_session(self, title: str) -> str:
        """同步实现,跑在 threadpool worker。"""
        safe_title = title if title else _DEFAULT_TITLE
        session = self._sessions.create(title=safe_title)
        return str(session.id)
    
    # ... 其他 6 个方法同模式(list_sessions / get_session / update_session /
    #     delete_session / append_message / get_messages)
```

### 3.3 MemoryStorageAdapter 改写模板

```python
class MemoryStorageAdapter:
    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionState] = {}
        self._counter: int = 0
    
    async def create_session(self, title: str = "") -> str:
        return await asyncio.to_thread(self._sync_create_session, title)
    
    def _sync_create_session(self, title: str) -> str:
        """同步实现,跑在 threadpool worker。无锁(纯内存操作)。"""
        self._counter += 1
        session_id = f"mem-{self._counter}"
        self._sessions[session_id] = _SessionState(title=title)
        return session_id
    
    # ... 其他 6 个方法同模式
```

### 3.4 锁归属（关键设计决策）

**两把锁已统一为 module-level `backend.data.database._SQLITE_LOCK = threading.Lock()`**,PR A handler(`@with_db_lock` 装饰器)和 PR B `SqliteStorageAdapter._sync_X`(在 `asyncio.to_thread` worker 内)共享同一把锁。

理由：

- 单一 lock 在所有同步 SQLite 写必经之路上,串行化访问同一 `sqlite3.Connection(check_same_thread=False)`
- 必须用 `threading.Lock` 而不是 `asyncio.Lock`: `_sync_X` 跑在线程池 worker 线程上,与 PR A 的 sync def handler 共享同一线程上下文; `asyncio.Lock` 只能保护 event loop 上的协程,看不到 worker 线程
- 锁位置选 `backend/data/database.py` 模块:database 层是所有 SQLite 访问的必经之地(adapter 通过 SessionRepository/MessageRepository、handler 直接 repo 都收敛到这里),放这里最自然
- PR A 的 `_db_lock` (在 `backend/api/legacy_routes.py`) 现在改 import `_SQLITE_LOCK as _db_lock`,`@with_db_lock` 装饰器 / `with _db_lock:` 调用点不动
- `MemoryStorageAdapter` 不加锁:纯内存 dict 操作,无并发问题

## 4. 组件与改动清单

| Component | Action | 改动量预估 |
|---|---|---|
| `backend/data/database.py` | **新增** | 模块级 `_SQLITE_LOCK = threading.Lock()`,所有 SQLite 写必经之路 |
| `backend/adapters/out/storage/sqlite_adapter.py` | 改写 | 7 个 async 方法 → 7 个包装 + 7 个 `_sync_X` 同步助手,`_sync_X` 内 `with _SQLITE_LOCK:`,移除 `self._lock`,docstring 更新 |
| `backend/adapters/out/storage/memory_adapter.py` | 改写 | 7 个 async 方法 → 7 个包装 + 7 个 `_sync_X` 同步助手,`_sync_create_session` 改 `uuid.uuid4()`,docstring 更新 |
| `backend/ports/storage.py` (StoragePort) | **不动** | 接口签名不变 |
| `backend/application/services/chat_service.py` | **不动** | 仍 `await storage.X()`,adapter 自动 offload |
| `backend/application/services/session_service.py` | **不动** | 同上 |
| `backend/main.py` | **不动** | DI 注入不变 |
| `backend/data/session_repo.py` | **不动** | SessionRepository 保持同步实现 |
| `backend/api/legacy_routes.py` | **改** | 改 `_db_lock` 为 `from backend.data.database import _SQLITE_LOCK as _db_lock`,`@with_db_lock` 装饰器签名不变 |
| `backend/tests/unit/test_memory_storage_adapter.py` | 扩展 | 新增 6-8 个单元测试 + 1 个并发无重复 ID 测试 |
| `backend/tests/integration/test_event_loop_blocking.py` | 扩展 | 新增 1 个跨路径并发回归测试(PR A handler + PR B adapter) |

**预计 diff**：~200 行新增（含注释和测试），0 行删除（改写 = 原方法名保留,内部实现替换）。

## 5. 数据流详解（典型链路：chat_stream_create）

```python
# FastAPI handler (async def, keep_async from PR A)
@router.post("/chat/stream_create")
async def chat_stream_create(...):
    session_id = await chat_service.create_session(...)  # ← 入口
    ...

# chat_service (不动)
class ChatService:
    async def create_session(self, title: str) -> str:
        session_id = await self.storage.create_session(title=title)  # ← await 不变
        return session_id

# SqliteStorageAdapter (PR B 改写)
class SqliteStorageAdapter:
    async def create_session(self, title: str = "") -> str:
        async with self._lock:                                          # ① 拿锁(线程内)
            return await asyncio.to_thread(self._sync_create_session, title)  # ② offload
    
    def _sync_create_session(self, title: str) -> str:                 # ③ 同步实现
        safe_title = title if title else _DEFAULT_TITLE
        session = self._sessions.create(title=safe_title)
        return str(session.id)
```

执行栈（50 并发 chat_stream_create 时）：

1. 事件循环收到 50 个请求，调度 chat_service.create_session
2. chat_service `await self.storage.create_session(...)` → 进入 adapter 包装
3. adapter `async with self._lock` → 锁按 FIFO 排队（每次只 1 个 worker 进 `_sync_X`）
4. adapter `await asyncio.to_thread(...)` → 把 `_sync_create_session` 投到 anyio threadpool
5. threadpool worker 执行 `_sync_create_session` → 调 `SessionRepository.create`（同步 SQLite 写，**不阻塞事件循环**）
6. 返回结果 → bubble up → SSE 推送
7. 锁释放 → 下一个 worker 进

事件循环整个期间**只在 adapter 包装那几行 Python 字节码上跑**（加锁 + asyncio.to_thread 调度，都是微秒级），`/health` handler 始终能立即响应 → P99 < 100ms。

## 6. 错误处理

| 失败场景 | 行为 |
|---|---|
| `_sync_X` 抛 `sqlite3.OperationalError` | `asyncio.to_thread` 不吞异常 → bubble up → FastAPI → 500（与原行为一致） |
| `_sync_X` 抛 `sqlite3.IntegrityError`（UNIQUE 冲突等） | 同上,传播 |
| `_sync_X` 抛 `ValueError` / `TypeError`（业务校验） | 同上 |
| `_lock` 等待超时 | 无超时（`asyncio.Lock` 无 timeout 参数）；实际等待时间是锁 FIFO 长度 × 单次 SQLite 写延迟（~10ms）→ 50 并发最长 ~500ms,远低于 SSE handler 的 keepalive 阈值 |
| `asyncio.to_thread` 自身失败 | stdlib 异常处理路径,理论不可达 |
| CancelledError（客户端断连） | asyncio 内置处理：`to_thread` 返回的 future 被 cancel → `_sync_X` 不被中断（线程继续跑完）,调用者收到 `CancelledError` |

**与 PR A 行为一致**：错误处理路径不变、不引入新错误码、traceback 仍指向原 `_sync_X` 行。

### 6.1 MemoryStorageAdapter 取舍

- 内存操作本身 μs 级（dict 操作），`asyncio.to_thread` 切换线程 ~30μs 开销
- **仍然包**：保持与 SqliteStorageAdapter 同形、未来若 Memory 后端换 redis 同样行为、MemoryStorageAdapter 用于单测,to_thread 仍能让单测断言"adapter 真在 thread 跑"
- **不加锁**：纯内存 dict 无并发问题

## 7. 测试

### 7.1 Unit Tests（`backend/tests/unit/test_memory_storage_adapter.py` 扩展）

新增 6-8 个测试（不动现有断言）：

1. **`test_to_thread_actually_offloads_to_worker`** — 验证 adapter 方法真的在 worker 线程跑,不在主事件循环线程跑。注入探针到 `_sync_create_session` 记 `threading.get_ident()`,断言 != 主线程。
2. **`test_concurrent_writes_are_serialized_by_lock`** — N=20 并发 `create_session`,`_sync_create_session` 内 `time.sleep(0.005)` 模拟延迟,断言执行区间两两不重叠（锁串行）。
3. **`test_memory_adapter_uses_to_thread_without_lock`** — MemoryStorageAdapter 包 to_thread 但无锁,10 并发执行,所有 thread_id != 主线程,不验证重叠。
4. **`test_to_thread_propagates_sync_exceptions`** — `_sync_create_session` 抛 `sqlite3.IntegrityError`,`await adapter.create_session(...)` 同样抛 `IntegrityError`。
5. **`test_sqlite_adapter_all_methods_use_to_thread`** — 验证 7 个 SqliteStorageAdapter 方法都通过 `asyncio.to_thread`（monkeypatch `asyncio.to_thread` 计数）。
6. **`test_memory_adapter_all_methods_use_to_thread`** — 同上,7 个方法。
7. **`test_lock_does_not_deadlock_under_high_concurrency`** — 100 并发同一方法,验证全部完成且锁未死锁（timeout 10s）。
8. **`test_lock_serializes_across_methods`** — N 并发混合调 `create_session` / `update_session` / `delete_session`,验证任意两个方法执行区间不重叠。

### 7.2 Integration Tests（`backend/tests/integration/test_event_loop_blocking.py` 扩展）

沿用 PR A 的 `/health` 探针 + 高并发 POST 模式,新增 1 个 chat_stream 场景：

**`test_health_latency_under_concurrent_chat_stream_create`** — N=50 并发 `POST /api/v1/chat/stream_create` 期间,`/health` P99 < 100ms。

前置依赖：
- `conftest.py` 需有 `mock_llm` fixture：返回固定 `mock response`,让 chat_service 不真调 LLM（PR B 实施时检查,可能需要新增）

### 7.3 CI 配置

不需要改 `.github/workflows/ci.yml`：现有 pytest integration job 自动跑 integration 标记的测试,新 test 自动包含。

## 8. 风险评估与依赖

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `mock_llm` fixture 缺失 | 中 | 中 | PR B 实施时优先检查 conftest.py,缺失则一并加(mock 不复杂) |
| `asyncio.to_thread` 切换开销导致单次 chat_stream 延迟增加 | 低 | 低 | 切换 ~30μs,远低于 LLM 调用的秒级延迟;且与 SQLite 写串行化前同量级 |
| 锁串行化导致 50+ 并发 chat_stream_create 排队 | 低 | 低 | PR A 已验证 50 并发 session CRUD 在锁串行下 < 500ms,chat_stream 比 session 创建重但仍可控 |
| `chat_service` 内部有其他阻塞调用（json.dumps / 等） | 中 | 中 | PR B 严格限定在 adapter,如发现只记录到 follow-up,不在本 PR 修 |
| 现有 `test_memory_storage_adapter.py` 测试对 async 方法内部行为有假设 | 低 | 低 | PR B 改写后行为等价（to_thread 仍返回正确结果、异常仍传播）,现有断言不受影响 |

## 9. 实施步骤（分解为可独立验证的里程碑）

- [ ] M1: 探索完成（spec 文档已 review）
- [ ] M2: 改写 SqliteStorageAdapter(7 个方法 → 7 对 `_sync_X` + 7 个包装)
- [ ] M3: 改写 MemoryStorageAdapter(7 个方法 → 7 对 `_sync_X` + 7 个包装)
- [ ] M4: 扩展单元测试(6-8 个新 test)
- [ ] M5: 加 mock_llm fixture(conftest.py,如缺失)
- [ ] M6: 扩展集成测试(1 个 chat_stream 场景)
- [ ] M7: pytest backend/tests/ 全量绿
- [ ] M8: ruff check backend/ 全绿
- [ ] M9: PR review + merge → main
- [ ] M10: 内存沉淀 + MEMORY.md 索引更新
- [ ] M11: Win7 cherry-pick(待用户决策)

## 10. 后续 PR（不在本 PR 范围）

- **PR C**：wiki_routes 18 handler 分两类
- **PR D**：docs + doctor 三期 event_loop_blocking check
- **§1.1**：存量资产变现 + hex 迁移 plan

## 11. References

- `docs/plans/2026-08-09_feature-optimization-proposal.md` §1.2
- PR #294 §1.2 commit `6614facb` —— 姊妹篇,fix(event-loop) PR A
- PR #294 commit `42cf8c54` —— legacy_routes async→def + lock + jieba warm(本 PR 的模式蓝本)
- PR #294 commit `da3a9ab8` —— test CI 修复(本 PR 测试可借鉴)
- `backend/tests/integration/test_event_loop_blocking.py` —— 集成测试脚手架
- `backend/adapters/out/storage/sqlite_adapter.py:11-14` —— 现有 docstring 承认反模式(本 PR 直接采纳这个判断的反面)