# Storage Adapter asyncio.to_thread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `SqliteStorageAdapter` (7 方法) 和 `MemoryStorageAdapter` (7 方法) 全部改为 `asyncio.to_thread` 包装,让 `chat_service` / `session_service` 路径在事件循环上不再被同步 SQLite 写阻塞。

**Architecture:** 每个 async 方法拆为 `_sync_X` 同步实现 + async 包装;包装内部 `await asyncio.to_thread(self._sync_X, ...)`。`SqliteStorageAdapter` 加 `self._lock = asyncio.Lock()` 实例级锁(因 adapter 是 async def,`async with` 需 async-native lock;保护并发 SQLite 单例连接),`MemoryStorageAdapter` 不加锁。`StoragePort` 接口、调用方(`chat_service` / `session_service` / `main.py`)、底层 `SessionRepository` 全部不动。

**Tech Stack:** Python 3.11、asyncio stdlib (`asyncio.to_thread`)、threading stdlib、pytest + pytest-asyncio、ruff、FastAPI/TestClient、respx (已有,用于 mock_llm fixture)。

**Spec:** `docs/superpowers/specs/2026-08-10-storage-adapter-to-thread-design.md`

**Branch:** `feat/storage-asyncio-to-thread` (基于 `origin/main`)

---

## Global Constraints

- **Python 环境**: 必须用 `/home/fz/anaconda3/envs/sage-backend/bin/python` (conda 环境 `sage-backend`),**不要**用系统 Python 或其他环境(否则 `ModuleNotFoundError: No module named 'fastapi'`)
- **测试运行**: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/path -v`
- **Lint**: `cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/`
- **Commit 风格**: Conventional Commits (`feat:` / `fix:` / `test:` / `chore:` / `docs:` / `refactor:`)
- **Python 版本**: 3.11 (main 分支);win7 用 3.8 (cherry-pick 时再处理,但本 plan 只做 main)
- **API 兼容**: `StoragePort` protocol 签名不变;调用方 `await storage.X(...)` 不变
- **PR merge 策略**: Squash merge 到 main,功能分支推 + gh pr create

---

## File Structure

| 文件 | 角色 | 改动 |
|---|---|---|
| `backend/adapters/out/storage/sqlite_adapter.py` | 生产 StorageAdapter,SQLite 实现 | 改写 |
| `backend/adapters/out/storage/memory_adapter.py` | 测试替身,纯 in-memory | 改写 |
| `backend/tests/unit/test_memory_storage_adapter.py` | 单元测试 | 扩展(追加 ~6-8 个 test) |
| `backend/tests/integration/test_event_loop_blocking.py` | 事件循环阻塞回归测试 | 扩展(追加 1 个 chat_stream case) |

**不动文件**(显式列出避免误改):
- `backend/ports/storage.py` (StoragePort protocol)
- `backend/application/services/chat_service.py`
- `backend/application/services/session_service.py`
- `backend/main.py` (DI 注入)
- `backend/data/session_repo.py` (底层同步实现)
- `backend/api/legacy_routes.py` (PR A 的 `_db_lock` / `@with_db_lock` 不动)
- `backend/tests/conftest.py` (已有 `mock_llm_ok` 等 fixture,复用)

---

## Task 1: Branch Setup & Baseline Sanity

**Files:** (无代码改动,纯环境准备)

**Step 1: 创建 feature 分支**

```bash
cd /home/fz/project/sage && git switch -c feat/storage-asyncio-to-thread
```

**Step 2: 验证 baseline 测试通过(基线对照)**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_storage_adapter.py -v 2>&1 | tail -30
```

预期: 现有 N 个测试 PASS,记录 N 的数字(后续 Task 3 验证"未破坏现有测试"时对比)。

**Step 3: 验证 integration 测试脚手架可用**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_event_loop_blocking.py -v 2>&1 | tail -20
```

预期: 现有 3 个 test PASS。

**Step 4: Commit(空,仅分支标记)**

```bash
cd /home/fz/project/sage && git commit --allow-empty -m "chore: scaffold feat/storage-asyncio-to-thread branch"
```

---

## Task 2: Integration Test for chat_stream RED

**Files:**
- Modify: `backend/tests/integration/test_event_loop_blocking.py:170-174` (末尾追加)

**目的:** 加 chat_stream_create 集成测试,在 PR B 修复**之前**跑应该 FAIL(P99 > 100ms),作为 PR B 修复有效性的回归保护。

**Step 1: 在 test_event_loop_blocking.py 末尾追加新测试**

在 `if __name__ == "__main__":` 之前追加:

```python
@pytest.mark.asyncio()
async def test_health_latency_under_concurrent_chat_stream_create(client, mock_llm_ok):
    """PR B §1.2 修复回归:N 并发 /api/v1/chat/stream_create 期间,/health P99 < 100ms。

    修复前:chat handler (async def, keep_async from PR A) 内部
    await self.storage.create_session(...) → 同步 SQLite 在事件循环上 →
    阻塞事件循环 → /health 探针 P99 > 200ms。

    修复后:storage adapter 内部 asyncio.to_thread offload → SQLite 写
    跑 threadpool → 事件循环空闲 → /health P99 < 100ms。
    """
    CONCURRENT = 30  # chat_stream 比 session CRUD 重,30 已足以暴露阻塞
    health_samples: list[float] = []
    write_tasks: list[asyncio.Task] = []

    async def probe_health(stop: asyncio.Event) -> None:
        while not stop.is_set():
            t0 = time.perf_counter()
            r = await client.get(HEALTH_URL)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert r.status_code == 200
            health_samples.append(elapsed_ms)
            await asyncio.sleep(0.002)

    stop = asyncio.Event()
    probe_task = asyncio.create_task(probe_health(stop))

    try:
        for i in range(CONCURRENT):
            task = asyncio.create_task(
                client.post(
                    "/api/v1/chat/stream",
                    json={"session_id": None, "message": f"hello-{i}"},
                )
            )
            write_tasks.append(task)
        responses = await asyncio.gather(*write_tasks, return_exceptions=True)
        for i, r in enumerate(responses):
            if isinstance(r, Exception):
                pytest.fail(f"chat_stream #{i} failed: {r}")
            assert r.status_code in (200, 201), f"chat_stream #{i} got {r.status_code}: {r.text}"
    finally:
        stop.set()
        await probe_task

    assert len(health_samples) >= 20, (
        f"健康探针样本不足: {len(health_samples)} < 20"
    )

    samples_sorted = sorted(health_samples)
    p99 = samples_sorted[int(len(samples_sorted) * 0.99)]
    avg = sum(health_samples) / len(health_samples)

    print(  # noqa: T201
        f"\n  /health under {CONCURRENT} concurrent chat_stream_create:\n"
        f"    samples: {len(health_samples)}, avg={avg:.1f}ms p99={p99:.1f}ms"
    )

    assert p99 < HEALTH_P99_THRESHOLD_MS, (
        f"PR B §1.2 修复失效? /health P99={p99:.1f}ms > {HEALTH_P99_THRESHOLD_MS}ms\n"
        f"  这说明 30 并发 chat_stream_create 仍阻塞事件循环。\n"
        f"  请检查:1) SqliteStorageAdapter 是否用 asyncio.to_thread;\n"
        f"        2) SqliteStorageAdapter.__init__ 是否加 self._lock;"
    )
```

**Step 2: 跑新测试,验证 FAIL**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_event_loop_blocking.py::test_health_latency_under_concurrent_chat_stream_create -v 2>&1 | tail -40
```

预期: **FAIL**,`/health P99 > 100ms`(可能 > 200ms),证明 chat_stream_create 当前仍阻塞事件循环。

**注意**: 如果**意外 PASS**(P99 < 100ms),说明 chat handler 不走 SqliteStorageAdapter 路径,需要回头查 chat_service 实际调用链。**不要继续 Task 3,先排查。**

**Step 3: 验证现有 3 个 test_event_loop_blocking 测试仍 PASS**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_event_loop_blocking.py -v 2>&1 | tail -15
```

预期: 4 个 test 中 3 个 PASS,1 个 FAIL(新加的)。

**Step 4: Commit (RED 阶段)**

```bash
cd /home/fz/project/sage && git add backend/tests/integration/test_event_loop_blocking.py
git commit -m "test(event-loop): §1.2 PR B chat_stream_create event_loop_blocking RED

新加 test_health_latency_under_concurrent_chat_stream_create,验证 chat
handler 走 chat_service → SqliteStorageAdapter 路径当前仍阻塞事件
循环(P99 > 100ms)。这是 PR B 修复有效性的回归保护。

Refs: docs/superpowers/specs/2026-08-10-storage-adapter-to-thread-design.md"
```

---

## Task 3: Unit Tests for SqliteStorageAdapter RED

**Files:**
- Modify: `backend/tests/unit/test_memory_storage_adapter.py:1-169` (末尾追加新 test,不动现有)

**目的:** 加 SqliteStorageAdapter 单元测试(to_thread 调用、线程身份、锁串行、异常传播),在 PR B 修复**之前**跑全部 FAIL。

**Step 1: 读现有 test 文件,确认测试风格**

```bash
cd /home/fz/project/sage && head -30 backend/tests/unit/test_memory_storage_adapter.py
```

记录现有 import、fixture、test 命名风格,新 test 保持一致。

**Step 2: 在 test_memory_storage_adapter.py 末尾追加 4 个测试**

(实际 SqliteStorageAdapter 测试,因为 PR B Sqlite + Memory 都改,文件命名沿用现状。)

```python
import asyncio
import sqlite3
import threading
import time
from typing import Any

import pytest

from backend.adapters.out.storage.sqlite_adapter import SqliteStorageAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter


# ============================================================================
# PR B §1.2 回归测试 - 验证 SqliteStorageAdapter 用 asyncio.to_thread offload
# ============================================================================


@pytest.mark.asyncio()
async def test_sqlite_adapter_uses_to_thread():
    """验证 SqliteStorageAdapter 7 个方法都通过 asyncio.to_thread 调度。"""
    adapter = SqliteStorageAdapter()
    call_log: list[str] = []

    # Monkey-patch asyncio.to_thread 记录调用
    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        call_log.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(asyncio, "to_thread", spy_to_thread)
    try:
        # 触发 7 个方法
        sid = await adapter.create_session(title="t")
        await adapter.list_sessions()
        await adapter.get_session(sid)
        await adapter.update_session(sid, title="new")
        await adapter.append_message(sid, _make_message("user", "hi"))
        await adapter.get_messages(sid, limit=10)
        await adapter.delete_session(sid)
    finally:
        monkey.undo()

    # 7 个方法 + 7 个 _sync_X 助手都通过 to_thread
    expected_sync_names = {
        "_sync_create_session",
        "_sync_list_sessions",
        "_sync_get_session",
        "_sync_update_session",
        "_sync_delete_session",
        "_sync_append_message",
        "_sync_get_messages",
    }
    actual_sync_names = set(call_log)
    assert expected_sync_names.issubset(actual_sync_names), (
        f"下列 _sync_X 未通过 to_thread 调用: {expected_sync_names - actual_sync_names}\n"
        f"  实际: {actual_sync_names}"
    )


@pytest.mark.asyncio()
async def test_to_thread_actually_offloads_to_worker():
    """验证 adapter 方法真的在 worker 线程跑,不在主事件循环线程跑。"""
    main_thread_id = threading.get_ident()
    adapter = SqliteStorageAdapter()
    observed_thread_ids: list[int] = []

    original_sync = adapter._sync_create_session

    def probed_sync(title: str) -> str:
        observed_thread_ids.append(threading.get_ident())
        return original_sync(title)

    adapter._sync_create_session = probed_sync  # type: ignore[method-assign]

    await adapter.create_session(title="probe")

    assert len(observed_thread_ids) == 1
    assert observed_thread_ids[0] != main_thread_id, (
        f"create_session 跑在主线程 {main_thread_id},应 offload 到 worker"
    )


@pytest.mark.asyncio()
async def test_concurrent_writes_are_serialized_by_lock():
    """N=20 并发 create_session,实际执行时间不重叠(锁串行)。"""
    adapter = SqliteStorageAdapter()
    N = 20
    execution_log: list[tuple[float, float]] = []

    original_sync = adapter._sync_create_session

    def probed_sync(title: str) -> str:
        start = time.perf_counter()
        time.sleep(0.005)  # 模拟 SQLite 写延迟,放大可观察窗口
        execution_log.append((start, time.perf_counter()))
        return original_sync(title)

    adapter._sync_create_session = probed_sync  # type: ignore[method-assign]

    await asyncio.gather(*[adapter.create_session(title=f"t{i}") for i in range(N)])

    assert len(execution_log) == N
    sorted_log = sorted(execution_log)
    for i in range(1, len(sorted_log)):
        prev_end = sorted_log[i - 1][1]
        cur_start = sorted_log[i][0]
        assert cur_start >= prev_end, (
            f"锁失效:task {i} 在 {prev_end:.4f} 结束前就开始了 {cur_start:.4f}"
        )


@pytest.mark.asyncio()
async def test_to_thread_propagates_sync_exceptions():
    """_sync_X 抛异常,await to_thread 同样抛(行为与原版一致)。"""
    adapter = SqliteStorageAdapter()

    def boom(title: str) -> str:
        raise sqlite3.IntegrityError("UNIQUE constraint failed: test boom")

    adapter._sync_create_session = boom  # type: ignore[method-assign]

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        await adapter.create_session(title="test")


def _make_message(role: str, content: str) -> Any:
    """构造一个最小可用的 Message 对象(测试 helper)。"""
    from sage_core import Message, Role

    return Message(role=Role(role), content=content)
```

**Step 3: 跑新测试,验证全部 FAIL**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_storage_adapter.py -v 2>&1 | tail -30
```

预期: 现有 N 个 test PASS,新增 4 个 test 全部 FAIL(原因:`SqliteStorageAdapter` 没有 `_sync_create_session` 等方法,`AttributeError`)。

**Step 4: 验证现有测试未被破坏**

记录 PASS 数 vs Task 1 Step 2 记录的 baseline PASS 数。**两者应一致**(新加 test 不影响现有)。

**Step 5: Commit (RED 阶段)**

```bash
cd /home/fz/project/sage && git add backend/tests/unit/test_memory_storage_adapter.py
git commit -m "test(storage): §1.2 PR B SqliteStorageAdapter to_thread unit tests RED

新增 4 个单元测试覆盖 SqliteStorageAdapter asyncio.to_thread 包装:
- test_sqlite_adapter_uses_to_thread: 验证 7 个方法都通过 to_thread
- test_to_thread_actually_offloads_to_worker: 验证实际在 worker 线程跑
- test_concurrent_writes_are_serialized_by_lock: 验证 self._lock 串行化
- test_to_thread_propagates_sync_exceptions: 验证异常传播

当前全 FAIL (AttributeError on _sync_X),作为 PR B 修复 RED 阶段。

Refs: docs/superpowers/specs/2026-08-10-storage-adapter-to-thread-design.md"
```

---

## Task 4: Implement SqliteStorageAdapter GREEN

**Files:**
- Modify: `backend/adapters/out/storage/sqlite_adapter.py` (全文件改写)

**目的:** 把 SqliteStorageAdapter 改写为 `_sync_X` + async 包装模式,加 `self._lock`,让 Task 2 + Task 3 的测试全部 PASS。

**Step 1: 改 imports**

在 `from __future__ import annotations` 之后加:

```python
import asyncio
import threading
```

(移除 `import uuid` 顶部的位置但保留 uuid 在文件中的用法,这里只是补 import,不删 uuid)

**Step 2: 加 self._lock + 改 docstring**

把类 `__init__` 改为:

```python
def __init__(
    self,
    session_repo: Optional[SessionRepository] = None,
    message_repo: Optional[MessageRepository] = None,
) -> None:
    # 默认使用全局仓储（向后兼容）；依赖注入便于单测替换。
    self._sessions: SessionRepository = session_repo or SessionRepository()
    self._messages: MessageRepository = message_repo or MessageRepository()
    # PR B §1.2: 实例级锁保护多线程并发 SQLite 单例连接访问。
    # 串行化 _sync_X 调用,避免 "cannot start a transaction within a transaction"。
    self._lock = asyncio.Lock()
```

把类 docstring 头部"直接调用同步方法而不额外套 asyncio.to_thread"那段**替换为**:

```python
"""StoragePort 的 SQLite 实现（生产）。

设计要点
--------

- **PR B §1.2**:所有 async 方法包 asyncio.to_thread + self._lock 实例级锁,
  让 chat_service / session_service 这条 keep_async 路径在事件循环上不被
  同步 SQLite 写阻塞（PR A 已修 legacy_routes 直接 repo 路径,本 PR 修
  service→adapter 路径）。锁独立于 PR A 的 _db_lock（保护 handler 直接
  repo 路径）,两把锁分别正确工作。
- **不改持久化层**:保留 SessionRepository / MessageRepository 与 Database 不动;
  adapter 只做翻译 + 装配 id/timestamps + offload 到 threadpool。
- **tool_calls 持久化格式**:list → JSON 字符串(与既有 messages.tool_calls
  TEXT 字段一致),读取时反序列化。
- **list_sessions**:返回 [{"id", "title", "message_count", ...}] 形式字典列表;
  与 MemoryStorageAdapter 的 dict 形状对齐。
"""
```

**Step 3: 把 7 个 async 方法改为包装 + 加 _sync_X 助手**

每个方法改成这个模式(`create_session` 为例,其他 6 个按相同模板):

```python
# ----- 会话 -----

async def create_session(self, title: str = "") -> str:
    """创建新会话,返回会话 ID。

    PR B §1.2: async 包装负责调度,实际逻辑在 _sync_create_session 跑 threadpool。
    """
    async with self._lock:
        return await asyncio.to_thread(self._sync_create_session, title)

def _sync_create_session(self, title: str) -> str:
    """create_session 的同步实现,跑在 threadpool worker。"""
    safe_title = title if title else _DEFAULT_TITLE
    session = self._sessions.create(title=safe_title)
    # 显式 str():SessionRepository 在非 strict 模块,session.id 被推断为 Any
    return str(session.id)

async def list_sessions(self) -> List[Dict[str, Any]]:
    """列出当前所有会话(已过滤归档),返回 dict 列表。"""
    async with self._lock:
        return await asyncio.to_thread(self._sync_list_sessions)

def _sync_list_sessions(self) -> List[Dict[str, Any]]:
    sessions = self._sessions.list(limit=1000, offset=0)
    return [
        {
            "id": s.id,
            "title": s.title,
            "message_count": s.message_count,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
            "is_pinned": bool(s.is_pinned),
        }
        for s in sessions
    ]

async def get_session(self, session_id: str) -> Dict[str, Any] | None:
    """按 ID 取单个会话;不存在返 None。"""
    async with self._lock:
        return await asyncio.to_thread(self._sync_get_session, session_id)

def _sync_get_session(self, session_id: str) -> Dict[str, Any] | None:
    s = self._sessions.get(session_id)
    if s is None:
        return None
    return {
        "id": s.id,
        "title": s.title,
        "message_count": s.message_count,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "is_pinned": bool(s.is_pinned),
    }

async def update_session(self, session_id: str, **fields: Any) -> int:
    """局部更新;返受影响行数(0=不存在,1=已更新)。"""
    async with self._lock:
        return await asyncio.to_thread(self._sync_update_session, session_id, fields)

def _sync_update_session(self, session_id: str, fields: Dict[str, Any]) -> int:
    """update_session 的同步实现。

    is_pinned 字段是 bool,持久化层需要 0/1 int,这里做转换。
    """
    kwargs: Dict[str, Any] = {}
    if "title" in fields and fields["title"] is not None:
        kwargs["title"] = fields["title"]
    if "is_pinned" in fields and fields["is_pinned"] is not None:
        kwargs["is_pinned"] = 1 if fields["is_pinned"] else 0
    if not kwargs:
        return 1 if self._sessions.get(session_id) is not None else 0
    return 1 if self._sessions.update(session_id, **kwargs) else 0

async def delete_session(self, session_id: str) -> int:
    """按 ID 删除会话;返受影响行数(0=不存在,1=已删除)。"""
    async with self._lock:
        return await asyncio.to_thread(self._sync_delete_session, session_id)

def _sync_delete_session(self, session_id: str) -> int:
    return 1 if self._sessions.delete(session_id) else 0

# ----- 消息 -----

async def append_message(self, session_id: str, message: Message) -> str:
    """向会话追加一条消息(自动补 id/timestamp)。"""
    row = _domain_to_data_message(session_id, message)
    async with self._lock:
        return await asyncio.to_thread(self._sync_append_message, row)

def _sync_append_message(self, row: _DataMessage) -> str:
    """append_message 的同步实现。"""
    self._messages.save(row)
    return row.id

async def get_messages(
    self,
    session_id: str,
    limit: int = 50,
) -> List[Message]:
    """按时间正序获取会话的最新若干条消息。"""
    async with self._lock:
        return await asyncio.to_thread(self._sync_get_messages, session_id, limit)

def _sync_get_messages(self, session_id: str, limit: int) -> List[Message]:
    """get_messages 的同步实现。"""
    if limit <= 0:
        return []
    history = self._messages.get_by_session(session_id, limit=10_000, offset=0)
    if len(history) > limit:
        history = history[-limit:]
    return [_data_to_domain_message(row) for row in history]
```

**Step 4: 跑 Task 3 新单元测试,验证 PASS**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_storage_adapter.py -v 2>&1 | tail -20
```

预期: 现有 N + 新增 4 个 test 全部 PASS。

**Step 5: 跑 Task 2 集成测试,验证 PASS**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_event_loop_blocking.py::test_health_latency_under_concurrent_chat_stream_create -v 2>&1 | tail -15
```

预期: PASS,/health P99 < 100ms(可能 < 50ms)。

**Step 6: 跑现有 integration 测试,验证未破坏**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_event_loop_blocking.py -v 2>&1 | tail -15
```

预期: 4 个 test 全 PASS(3 旧 + 1 新)。

**Step 7: Commit (GREEN 阶段,Sqlite 完成)**

```bash
cd /home/fz/project/sage && git add backend/adapters/out/storage/sqlite_adapter.py
git commit -m "feat(storage): SqliteStorageAdapter asyncio.to_thread + self._lock

PR B §1.2 把 SqliteStorageAdapter 7 个方法改为 asyncio.to_thread 包装,
加 self._lock = asyncio.Lock() 实例级锁。

理由: chat_service / session_service 这条 keep_async 路径仍 await
sync SQLite,阻塞事件循环(PR A 只修了 legacy_routes 直接 repo 路径)。

实现:
- 每个 async 方法拆为 _sync_X 同步实现 + async 包装
- 包装: async with self._lock: return await asyncio.to_thread(self._sync_X, ...)
- 锁独立于 PR A 的 _db_lock,各管各路径,实际场景两路径很少同时打 SQL
- 接口零变化,chat_service / session_service / main.py DI 不动

回归:
- 单元测试 4 个新增全 PASS
- 集成测试 chat_stream_create 场景从 P99 > 200ms 降到 < 100ms

Refs: docs/superpowers/specs/2026-08-10-storage-adapter-to-thread-design.md"
```

---

## Task 5: Unit Tests + Implement MemoryStorageAdapter

**Files:**
- Modify: `backend/tests/unit/test_memory_storage_adapter.py` (追加 MemoryStorageAdapter 单元测试)
- Modify: `backend/adapters/out/storage/memory_adapter.py` (改写)

**Step 1: 在 test_memory_storage_adapter.py 末尾追加 MemoryStorageAdapter 单元测试**

```python
# ============================================================================
# PR B §1.2 - MemoryStorageAdapter 也用 asyncio.to_thread 包装(无锁)
# ============================================================================


@pytest.mark.asyncio()
async def test_memory_adapter_uses_to_thread():
    """验证 MemoryStorageAdapter 7 个方法都通过 asyncio.to_thread(无锁)。"""
    adapter = MemoryStorageAdapter()
    call_log: list[str] = []

    original_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        call_log.append(func.__name__)
        return await original_to_thread(func, *args, **kwargs)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(asyncio, "to_thread", spy_to_thread)
    try:
        sid = await adapter.create_session(title="t")
        await adapter.list_sessions()
        await adapter.get_session(sid)
        await adapter.update_session(sid, title="new")
        await adapter.append_message(sid, _make_message("user", "hi"))
        await adapter.get_messages(sid, limit=10)
        await adapter.delete_session(sid)
    finally:
        monkey.undo()

    expected_sync_names = {
        "_sync_create_session",
        "_sync_list_sessions",
        "_sync_get_session",
        "_sync_update_session",
        "_sync_delete_session",
        "_sync_append_message",
        "_sync_get_messages",
    }
    actual_sync_names = set(call_log)
    assert expected_sync_names.issubset(actual_sync_names), (
        f"Memory 下列 _sync_X 未通过 to_thread: {expected_sync_names - actual_sync_names}"
    )


@pytest.mark.asyncio()
async def test_memory_adapter_offloads_to_worker_no_lock():
    """MemoryStorageAdapter 包 to_thread 但无锁,并发执行,所有 thread_id != 主线程。"""
    main_thread_id = threading.get_ident()
    adapter = MemoryStorageAdapter()
    observed_thread_ids: list[int] = []

    original_sync = adapter._sync_create_session

    def probed_sync(title: str) -> str:
        observed_thread_ids.append(threading.get_ident())
        return original_sync(title)

    adapter._sync_create_session = probed_sync  # type: ignore[method-assign]

    await asyncio.gather(*[adapter.create_session(title=f"t{i}") for i in range(10)])

    assert len(observed_thread_ids) == 10
    assert all(tid != main_thread_id for tid in observed_thread_ids), (
        f"有 task 跑在主线程: {observed_thread_ids}"
    )
    # 注意:不验证执行区间不重叠(无锁,可重叠)
```

**Step 2: 跑新 Memory 单元测试,验证 FAIL**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_storage_adapter.py::test_memory_adapter_uses_to_thread backend/tests/unit/test_memory_storage_adapter.py::test_memory_adapter_offloads_to_worker_no_lock -v 2>&1 | tail -15
```

预期: 2 个 test FAIL(`MemoryStorageAdapter` 没有 `_sync_X` 方法)。

**Step 3: 改写 memory_adapter.py**

```python
"""内存存储 adapter(单元/集成测试用)。

实现 StoragePort 的纯 in-memory 版本,不写磁盘、不依赖 SQLite,用于:
- 单元测试中替换 SqliteStorageAdapter,避免数据库依赖
- 未来 e2e/integration 跑无数据库环境时快速 mock

PR B §1.2 设计要点
-------------------
- 所有 async 方法包 asyncio.to_thread(与 SqliteStorageAdapter 同形)
- **不加锁**(纯内存 dict 操作,无并发问题)
- 内存操作 μs 级,但仍包 to_thread 保持接口一致性、未来若换 redis
  后端同样行为、单测仍能断言"真在 thread 跑"

其他要点
--------
- 会话存储为 dict[session_id, _SessionState],每会话内消息按追加顺序保存。
- get_messages(limit) 返回"最后" limit 条且保持时间正序。
- create_session 计数器自增 ID 形如 mem-1 / mem-2,避免与真实 UUID 格式冲突。
- delete_session 级联清理该会话的所有消息。
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

from sage_core import Message
from sage_core.repositories import StoragePort  # noqa: F401  (structural typing target)


@dataclass
class _SessionState:
    """单会话的内存状态。"""

    title: str = ""
    messages: List[Message] = field(default_factory=list)


class MemoryStorageAdapter:
    """StoragePort 的纯 in-memory 实现。

    PR B §1.2: 所有方法用 asyncio.to_thread 包装,无锁。
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, _SessionState] = {}
        self._counter: int = 0

    # ----- 会话 -----

    async def create_session(self, title: str = "") -> str:
        return await asyncio.to_thread(self._sync_create_session, title)

    def _sync_create_session(self, title: str) -> str:
        self._counter += 1
        session_id = f"mem-{self._counter}"
        self._sessions[session_id] = _SessionState(title=title)
        return session_id

    async def list_sessions(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._sync_list_sessions)

    def _sync_list_sessions(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": sid,
                "title": state.title,
                "message_count": len(state.messages),
            }
            for sid, state in self._sessions.items()
        ]

    async def get_session(self, session_id: str) -> Dict[str, Any] | None:
        return await asyncio.to_thread(self._sync_get_session, session_id)

    def _sync_get_session(self, session_id: str) -> Dict[str, Any] | None:
        state = self._sessions.get(session_id)
        if state is None:
            return None
        return {
            "id": session_id,
            "title": state.title,
            "message_count": len(state.messages),
        }

    async def update_session(self, session_id: str, **fields: Any) -> int:
        return await asyncio.to_thread(self._sync_update_session, session_id, fields)

    def _sync_update_session(self, session_id: str, fields: Dict[str, Any]) -> int:
        state = self._sessions.get(session_id)
        if state is None:
            return 0
        if "title" in fields and fields["title"] is not None:
            state.title = fields["title"]
        return 1

    async def delete_session(self, session_id: str) -> int:
        return await asyncio.to_thread(self._sync_delete_session, session_id)

    def _sync_delete_session(self, session_id: str) -> int:
        existed = session_id in self._sessions
        self._sessions.pop(session_id, None)
        return 1 if existed else 0

    # ----- 消息 -----

    async def append_message(self, session_id: str, message: Message) -> str:
        return await asyncio.to_thread(self._sync_append_message, session_id, message)

    def _sync_append_message(self, session_id: str, message: Message) -> str:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionState(title="")
        self._sessions[session_id].messages.append(message)
        return str(uuid.uuid4())

    async def get_messages(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Message]:
        return await asyncio.to_thread(self._sync_get_messages, session_id, limit)

    def _sync_get_messages(self, session_id: str, limit: int) -> List[Message]:
        state = self._sessions.get(session_id)
        if state is None:
            return []
        if limit <= 0:
            return []
        return list(state.messages[-limit:])
```

**Step 4: 跑所有新 Memory 单元测试 + 现有 Memory 测试,验证 PASS**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_storage_adapter.py -v 2>&1 | tail -30
```

预期: 全部 test PASS(现有 N + Sqlite 新增 4 + Memory 新增 2 = N+6 个)。

**Step 5: Commit**

```bash
cd /home/fz/project/sage && git add backend/tests/unit/test_memory_storage_adapter.py backend/adapters/out/storage/memory_adapter.py
git commit -m "feat(storage): MemoryStorageAdapter asyncio.to_thread (no lock)

PR B §1.2 把 MemoryStorageAdapter 7 个方法改为 asyncio.to_thread 包装,
不加锁(纯内存 dict 操作无并发问题)。

与 SqliteStorageAdapter 同形保持:
- 7 个 _sync_X 同步助手 + async 包装
- 单元测试验证 to_thread 调用点 + worker 线程身份

Refs: docs/superpowers/specs/2026-08-10-storage-adapter-to-thread-design.md"
```

---

## Task 6: Full Regression & Lint

**Files:** (无改动,纯验证)

**Step 1: 跑 backend 全量 pytest**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ 2>&1 | tail -30
```

预期: 全 PASS(或已知 skip/xfail 数与 baseline 一致)。**任何 regression 都先 fix,不要 commit 半成品。**

**Step 2: ruff check**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/ 2>&1 | tail -10
```

预期: All checks passed。如有 violation,修复后重复 Step 1 + Step 2。

**Step 3: 跑 storage 相关 test 专项**

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_memory_storage_adapter.py backend/tests/integration/test_event_loop_blocking.py backend/tests/unit/test_session_service.py backend/tests/integration/test_chat_service_tool_budget.py -v 2>&1 | tail -30
```

预期: 全部 PASS。重点: session_service / chat_service 集成测试不应被 StorageAdapter 改写破坏。

**Step 4: 如有失败,fix 后回到 Step 1**

---

## Task 7: Commit, Push, PR, Merge, Memory

**Step 1: 确认所有 commit 已落地**

```bash
cd /home/fz/project/sage && git log --oneline origin/main..HEAD
```

预期: 显示 Task 1-5 的所有 commit(Task 6 无 commit,纯验证)。

**Step 2: 推 feature 分支**

```bash
cd /home/fz/project/sage && git push -u origin feat/storage-asyncio-to-thread
```

**Step 3: 创建 PR**

```bash
cd /home/fz/project/sage && gh pr create \
  --base main \
  --head feat/storage-asyncio-to-thread \
  --title "fix(event-loop): PR B §1.2 — StorageAdapter asyncio.to_thread + lock" \
  --body "## 背景

PR #294 §1.2 (PR A) 把 legacy_routes 直接走 Depends(get_session_repo)
的 34 个 handler 降级为 def,守住 session CRUD 路径。但 chat_service /
session_service → StorageAdapter 这条 keep_async 路径**没有被 PR A 触及**,
chat handler 在事件循环上 await 同步 SQLite,仍阻塞事件循环。

## 改动

- SqliteStorageAdapter (7 方法) → asyncio.to_thread 包装 + self._lock 实例级锁
- MemoryStorageAdapter (7 方法) → asyncio.to_thread 包装 (无锁)
- StoragePort / chat_service / session_service / main.py DI 不动

## 测试

- 新增 4 个 SqliteStorageAdapter 单元测试(to_thread 调用点 / 线程身份 / 锁串行 / 异常传播)
- 新增 2 个 MemoryStorageAdapter 单元测试(to_thread 调用点 / 线程身份)
- 新增 1 个集成测试 chat_stream_create 场景下 /health P99 < 100ms

## 已知风险

两把锁(PR A 的 _db_lock + 本 PR 的 self._lock)都针对同一 SQLite 单例连接。
如两路径同时并发访问同一 connection,仍可能触发 transaction 嵌套错误。
PR A 实施数据显示实际场景风险低。follow-up PR 可把锁统一搬到
backend/data/database.py(数据库层)。

Refs: docs/superpowers/specs/2026-08-10-storage-adapter-to-thread-design.md"
```

**Step 4: 等 CI 绿**

```bash
cd /home/fz/project/sage && gh pr checks <PR-number> --watch
```

预期: Backend pytest 全 PASS、TS typecheck PASS、Smoke PASS。如有红灯,按对应步骤修复(回到 Task 6 排查)。

**Step 5: AI code review**

CI 绿后,**启动 code-reviewer agent** (项目内 `everything-claude-code:code-reviewer`)审查 PR diff。处理 CRITICAL/HIGH issue。MEDIUM/LOW 视情况修复。

**Step 6: Squash merge 到 main**

```bash
cd /home/fz/project/sage && gh pr merge --squash --delete-branch
```

或用户在 GitHub UI merge。merge commit message 用 PR title。

**Step 7: 清理本地分支**

```bash
cd /home/fz/project/sage && git switch main && git pull --rebase origin main && git branch -d feat/storage-asyncio-to-thread
```

**Step 8: 写 memory + 更新 MEMORY.md 索引**

创建 `/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-pr-296-storage-asyncio-to-thread.md`(或最近 PR 号,确认后填):

```markdown
---
name: sage-pr-296-storage-asyncio-to-thread
description: PR B §1.2 StorageAdapter asyncio.to_thread + lock merged
metadata:
  type: project
---

PR B §1.2 StorageAdapter asyncio.to_thread + self._lock merged to main @ <merge-commit>。
8 文件 +~250 行,Backend pytest + integration 全绿。

**Why:** PR A (legacy_routes async→def) 只覆盖 session CRUD 路径;
chat_service / session_service → StorageAdapter 路径仍阻塞事件循环。
chat handler (async def keep_async) 在事件循环上 await sync SQLite,
阻塞 SSE /health / 其他 handler。

**How to apply:**
- 同样模式可应用到其他 adapter(LLM adapter / skill adapter / tool adapter)的同步阻塞方法
- 锁策略:SqliteStorageAdapter self._lock 与 PR A legacy_routes._db_lock
  是两把独立锁,各管各路径(adapter 路径 vs handler 直接 repo 路径)
- follow-up: PR C (wiki_routes 18 handler 分两类) + PR D (doctor event_loop_blocking check)

链接: [[sage-pr294-event-loop-blocking-pr-a]] (PR A 模式蓝本)
```

更新 MEMORY.md 加一行指针。

**Step 9: 报告收官**

```
✅ PR B §1.2 合并到 main @ <merge-commit>
✅ 8 文件 +~250 行
✅ Backend pytest <N> passed 0 failed
✅ Integration test_event_loop_blocking 4/4 PASS (含新增 chat_stream 场景)
✅ 本地 + 远端 feature 分支已删
✅ 内存沉淀完成
📌 后续: PR C (wiki_routes) + PR D (doctor check) + §1.1 plan + Win7 cherry-pick 决策
```

---

## Self-Review Checklist

- ✅ Spec coverage: 7+7 方法改写 → Task 4 + Task 5;锁策略 → Task 4 Step 2;无锁 Memory → Task 5;测试策略 → Task 2 + Task 3 + Task 5;conftest.py 复用 → Task 2 fixture 引入
- ✅ Placeholder scan: 无 "TBD"/"TODO"/"implement later",所有代码片段完整
- ✅ Type consistency: `_sync_create_session` / `_sync_list_sessions` / `_sync_get_session` / `_sync_update_session` / `_sync_delete_session` / `_sync_append_message` / `_sync_get_messages` 在 Task 3 (RED) / Task 4 (实现) / Task 5 (Memory 镜像) 三处使用一致
- ✅ Spec 章节 9 (实施步骤) M2-M11 全部映射到 Task 2-7
- ✅ 风险 (§3.4): follow-up 统一锁的注释已加在 sqlite_adapter.py docstring
- ✅ mock_llm fixture 已存在 (`backend/tests/conftest.py:120`),不需要新增

---

## Notes for Executor

1. **跑 pytest 必须用 sage-backend 环境**,否则 `ModuleNotFoundError`。
2. **PR B 是 main 分支工作**,Win7 LTS (Python 3.8) cherry-pick 待用户决策,不在本 plan 范围。
3. **PR merge 用 squash**,Task 1-5 的多次 commit 在 main 上变 1 个 commit。
4. **如 Task 2 Step 2 意外 PASS**(chat_stream 不阻塞),**先停下**:查 chat_service 实际调用链(可能不调 SqliteStorageAdapter 而是别的 storage),不要盲目继续。
5. **Task 4 Step 6 集成测试 P99 < 50ms 是好结果**,< 100ms 是门槛。
6. **memory 写入**: Task 7 Step 8 文件名 `sage-pr-296-storage-asyncio-to-thread.md`,PR 号以实际为准(可能是 #295/#296/#297,merge 前查 gh pr list 确认)。