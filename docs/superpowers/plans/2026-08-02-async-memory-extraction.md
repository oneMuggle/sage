# 记忆提取异步化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让记忆事实提取（含一次 LLM 调用）脱离聊天响应关键路径——hex `run_turn` 第 7 步与 legacy `_extract_legacy_chat_memory` 不再 inline await 提取，统一投递到后台单 worker 队列串行消费。

**Architecture:** 新增 `backend/memory/async_extractor.py` 提供 `MemoryExtractionQueue`（非阻塞 `submit` + 单 `_worker` + `drain` + 计数器 + 全局单例），worker 复用现有模块级 `extract_and_store_memory` 统一写入路径。hex/legacy 两个调用点改为 `queue.submit(...)` 不 await。worker 在 submit 时懒启动（幂等），main.py lifespan 显式 start/stop。

**Tech Stack:** Python 3.11 + asyncio（`asyncio.Queue` / `asyncio.create_task` / `asyncio.wait_for`）+ pytest-asyncio。与 `backend/application/services/file_mutation_queue.py`（A26）同构，但 `submit` 非阻塞（不等结果）。

**Spec:** `docs/superpowers/specs/2026-08-02-memory-extraction-async-design.md`

## Global Constraints

- **六边形纯净**：`backend/memory/` 层不 import FastAPI（BackgroundTasks 方案已否决）。
- **best-effort 契约**：任何提取失败只 `logger.warning`，绝不外抛；不得破坏聊天轮次/流式响应。
- **复用统一写入路径**：worker 内必须调用 `backend.application.services.chat_service.extract_and_store_memory`（懒导入防循环 import），不重写提取逻辑。
- **`extract_and_store_memory` 自身逻辑单测保持不动**（`test_chat_service_snapshot.py` 不改）。
- **提交端前置过滤**：`memory_port is None` 或 `enabled=False` → 计 `skipped`，不入队。
- **单 worker 串行**：不得加第二 worker（顺序保证 + 背压）。
- **Python 环境**：所有 pytest 用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`（conda `sage-backend`，Python 3.11）。

---

### Task 1: 新增 `MemoryExtractionQueue` 模块 + 单测

**Files:**
- Create: `backend/memory/async_extractor.py`
- Modify: `backend/tests/conftest.py`（`setup_test_db` 里重置队列单例）
- Test: `backend/tests/unit/test_async_extractor.py`

**Interfaces:**
- Produces（供 Task 2/3/4 依赖）:
  - `ExtractionRequest(memory_port, extractor, user_text, assistant_text, session_id, enabled)` — frozen dataclass
  - `MemoryExtractionQueue.submit(request) -> None` — 非阻塞；None port / disabled 计 `skipped`
  - `MemoryExtractionQueue.start() -> None` — 幂等启动 worker
  - `MemoryExtractionQueue.stop() -> None` — 取消 worker
  - `await MemoryExtractionQueue.drain(timeout=5.0)` — 等队列清空 + 处理完成；超时不抛
  - `pending() -> int`、`.completed` / `.failed` / `.skipped`（属性）
  - `get_memory_extraction_queue() -> MemoryExtractionQueue`、`reset_memory_extraction_queue() -> None`（全局单例）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/unit/test_async_extractor.py`:

```python
"""Unit tests for MemoryExtractionQueue — 记忆提取异步化队列。"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from backend.memory.async_extractor import (
    ExtractionRequest,
    get_memory_extraction_queue,
    reset_memory_extraction_queue,
)


@pytest.fixture()
def queue():
    reset_memory_extraction_queue()
    yield get_memory_extraction_queue()
    reset_memory_extraction_queue()


def _req(memory=None, enabled=True, text="用户想吃火锅"):
    memory = memory if memory is not None else AsyncMock(spec=object)
    return ExtractionRequest(
        memory_port=memory,
        extractor=AsyncMock(),
        user_text=text,
        assistant_text="好的",
        session_id="s1",
        enabled=enabled,
    )


@pytest.mark.asyncio()
async def test_submit_is_non_blocking(queue):
    """submit 立即返回，提取在后台 worker 执行（不在 submit 内）。"""
    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=AsyncMock(),
    ) as mock_extract:
        queue.submit(_req())
        assert mock_extract.await_count == 0  # 未同步执行
        await queue.drain()
        assert mock_extract.await_count == 1


@pytest.mark.asyncio()
async def test_worker_passes_request_through(queue):
    """worker 把请求原样透传给 extract_and_store_memory。"""
    req = _req()
    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=AsyncMock(),
    ) as mock_extract:
        queue.submit(req)
        await queue.drain()
        mock_extract.assert_awaited_once()
        call = mock_extract.await_args[1]
        assert call["memory_port"] is req.memory_port
        assert call["session_id"] == "s1"


@pytest.mark.asyncio()
async def test_submits_processed_in_order(queue):
    """多请求按提交顺序消费。"""
    order = []

    async def fake_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        order.append(user_text)
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=fake_extract,
    ):
        queue.submit(_req(text="第一"))
        queue.submit(_req(text="第二"))
        queue.submit(_req(text="第三"))
        await queue.drain()
    assert order == ["第一", "第二", "第三"]


@pytest.mark.asyncio()
async def test_single_worker_serial(queue):
    """并发 submit 不并发执行（单 worker 串行）。"""
    active = 0
    max_active = 0

    async def fake_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=fake_extract,
    ):
        for i in range(5):
            queue.submit(_req(text=f"m{i}"))
        await queue.drain()
    assert max_active == 1


@pytest.mark.asyncio()
async def test_worker_survives_single_failure(queue):
    """单条失败不杀 worker，后续项继续，failed 计数 +1。"""

    async def fake_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        if user_text == "boom":
            raise RuntimeError("extractor boom")
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=fake_extract,
    ):
        queue.submit(_req(text="boom"))
        queue.submit(_req(text="ok"))
        await queue.drain()
    assert queue.failed == 1
    assert queue.completed == 1


@pytest.mark.asyncio()
async def test_drain_waits_and_times_out_gracefully(queue):
    """drain 等待完成；超时返回不抛，worker 存活继续处理。"""

    async def slow_extract(memory_port, extractor, user_text, assistant_text, session_id, enabled):
        await asyncio.sleep(0.5)
        return 1

    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=slow_extract,
    ):
        queue.submit(_req())
        await queue.drain(timeout=0.05)  # 超时返回，不抛
        await queue.drain(timeout=2.0)  # worker 存活，等慢任务完成
    assert queue.completed == 1


@pytest.mark.asyncio()
async def test_submit_filters_disabled_and_none(queue):
    """memory_port=None / enabled=False → skipped，不入队。"""
    with patch(
        "backend.application.services.chat_service.extract_and_store_memory",
        new=AsyncMock(),
    ) as mock_extract:
        queue.submit(_req(memory=None))
        queue.submit(_req(enabled=False))
        await queue.drain()
    assert queue.skipped == 2
    assert queue.pending() == 0
    assert mock_extract.await_count == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_async_extractor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.memory.async_extractor'`

- [ ] **Step 3: 写最小实现**

创建 `backend/memory/async_extractor.py`:

```python
"""异步记忆提取队列 — 让聊天响应关键路径不再等待 LLM 事实提取。

把 ``extract_and_store_memory``（含一次 LLM 调用）从 hex ``run_turn``
第 7 步与 legacy ``_extract_legacy_chat_memory`` 的 inline await 中
剥离出来，投递到本队列由**单 worker** 串行消费：

- 顺序保证 + 天然背压：单 worker 串行，LLM 提取本就慢，并发只会叠加负载
- best-effort：任何失败只 warning，绝不外抛、不影响聊天
- 可测试：``drain()`` 等待队列清空 + worker 空闲，测试可确定性断言
- 六边形纯净：不依赖 FastAPI（``BackgroundTasks`` 方案已评估否决）

与 ``file_mutation_queue.py``（A26）同构，但 ``submit`` 是**非阻塞**
（只入队即返回，不等结果）—— 记忆提取不需要调用方等待结果。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionRequest:
    """一次记忆提取请求（与 ``extract_and_store_memory`` 参数同构）。"""

    memory_port: Any
    extractor: Any
    user_text: str
    assistant_text: str
    session_id: Optional[str]
    enabled: bool


class MemoryExtractionQueue:
    """异步记忆提取队列（单 worker 串行消费）。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ExtractionRequest] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._completed = 0
        self._failed = 0
        self._skipped = 0

    # ---- 公共 API ------------------------------------------------------- #

    def submit(self, request: ExtractionRequest) -> None:
        """非阻塞投递提取请求；无效请求（None port / disabled）直接跳过。"""
        if request.memory_port is None or not request.enabled:
            self._skipped += 1
            return
        self._queue.put_nowait(request)
        self._ensure_worker()

    def start(self) -> None:
        """确保 worker 已启动（幂等；main.py lifespan 调用）。"""
        self._ensure_worker()

    def stop(self) -> None:
        """取消 worker 任务（生产 shutdown 用）。"""
        if self._worker_task is not None and not self._worker_task.done():
            with contextlib.suppress(Exception):
                self._worker_task.cancel()
        self._worker_task = None

    async def drain(self, timeout: float = 5.0) -> None:
        """等待队列清空 + 所有项处理完成；超时返回（best-effort，不抛）。"""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except Exception:  # noqa: BLE001 - best-effort，超时/异常都不外抛
            logger.debug("memory extraction drain timed out after %.1fs", timeout)

    def pending(self) -> int:
        """当前排队未处理的请求数。"""
        return self._queue.qsize()

    @property
    def completed(self) -> int:
        return self._completed

    @property
    def failed(self) -> int:
        return self._failed

    @property
    def skipped(self) -> int:
        return self._skipped

    # ---- 内部实现 ------------------------------------------------------- #

    def _ensure_worker(self) -> None:
        """懒启动 worker（幂等）；submit 与 start 共用。"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(
                self._worker(), name="memory-extraction-worker"
            )

    async def _worker(self) -> None:
        """单 worker 循环：消费队列 → 提取 → 失败隔离。"""
        while True:
            try:
                request = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                await self._process(request)
                self._completed += 1
            except Exception as exc:  # noqa: BLE001 - 单条失败不杀 worker
                self._failed += 1
                logger.warning(
                    "memory extraction failed (session=%s): %s",
                    request.session_id,
                    exc,
                )
            finally:
                self._queue.task_done()

    async def _process(self, request: ExtractionRequest) -> None:
        """复用 hex/legacy 共用的统一写入路径（worker 内惰性导入防循环）。"""
        from backend.application.services.chat_service import extract_and_store_memory

        await extract_and_store_memory(
            memory_port=request.memory_port,
            extractor=request.extractor,
            user_text=request.user_text,
            assistant_text=request.assistant_text,
            session_id=request.session_id,
            enabled=request.enabled,
        )


# 全局单例（与 get_usage_store 同模式）
_extraction_queue: Optional[MemoryExtractionQueue] = None


def get_memory_extraction_queue() -> MemoryExtractionQueue:
    """获取全局 MemoryExtractionQueue 单例。"""
    global _extraction_queue
    if _extraction_queue is None:
        _extraction_queue = MemoryExtractionQueue()
    return _extraction_queue


def reset_memory_extraction_queue() -> None:
    """重置单例并取消残留 worker（仅测试用）。"""
    global _extraction_queue
    if _extraction_queue is not None:
        _extraction_queue.stop()
        _extraction_queue = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_async_extractor.py -v`
Expected: PASS — 7/7 绿

- [ ] **Step 5: conftest 重置队列单例（测试隔离）**

在 `backend/tests/conftest.py` 的 `setup_test_db` 中，`reset_usage_store()` 之后追加：

```python
    # MemoryExtractionQueue 单例绑定全局事件循环，必须随测试重置
    # （取消残留 worker，避免跨测试泄漏 + "task was destroyed" 警告）
    from backend.memory.async_extractor import reset_memory_extraction_queue

    reset_memory_extraction_queue()
```

- [ ] **Step 6: 跑全量单测确认无回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -q`
Expected: PASS — 无回归（现有测试不引用新模块）

- [ ] **Step 7: Commit**

```bash
git add backend/memory/async_extractor.py backend/tests/unit/test_async_extractor.py backend/tests/conftest.py
git commit -m "feat: 异步记忆提取队列 MemoryExtractionQueue（单 worker + drain）"
```

---

### Task 2: hex `run_turn` 第 7 步 → `queue.submit`（适配 test_chat_service_memory.py）

**Files:**
- Modify: `backend/application/services/chat_service.py`（`_run_turn_inner` 第 7 步，~line 452-464）
- Modify: `backend/tests/unit/test_chat_service_memory.py`（2 处加 drain）
- Test: `backend/tests/unit/test_chat_service_memory.py`

**Interfaces:**
- Consumes: `ExtractionRequest` / `get_memory_extraction_queue()`（Task 1）
- Produces: hex 路径改为非阻塞 submit；移除 `memory.stored_facts` span 属性

- [ ] **Step 1: 改 hex 路径为 submit（先改实现，后适配测试——因断言语义变化）**

`backend/application/services/chat_service.py`，`_run_turn_inner` 第 7 步，替换为：

```python
        if self.memory:
            from backend.memory.async_extractor import (
                ExtractionRequest,
                get_memory_extraction_queue,
            )
            from backend.memory.extractor import MemoryExtractor

            # 记忆提取异步化：投递到后台队列由单 worker 串行消费，
            # 不阻塞本轮聊天响应（提取含一次 LLM 调用）。
            get_memory_extraction_queue().submit(
                ExtractionRequest(
                    memory_port=self.memory,
                    extractor=MemoryExtractor(llm_client=self.llm),
                    user_text=user_message.content or "",
                    # 剥离技能 nudge 后缀, 避免提示文本被提取为"记忆事实"（review LOW）
                    assistant_text=(response.content or "").replace(SKILL_NUDGE_SUFFIX, ""),
                    session_id=session_id,
                    enabled=True,  # hex 路径保持现状行为：有 memory 即写
                )
            )
```

同时删除原本的 `stored_facts = await extract_and_store_memory(...)` 调用与 `span.set_attribute("memory.stored_facts", stored_facts)` 行。

- [ ] **Step 2: 适配 test_chat_service_memory.py — 两处断言前加 drain**

文件顶部 import 追加：

```python
from backend.memory.async_extractor import get_memory_extraction_queue
```

`test_chat_service_stores_memory_after_chat`（~line 229）在 `run_turn` 之后、断言之前插入：

```python
        await chat_service_with_memory.run_turn("session-123", user_message)

        # 记忆提取已异步化：等后台 worker 消费完再断言落库效果
        await get_memory_extraction_queue().drain()
```

`test_chat_service_detects_preferences`（~line 257）同样在 `run_turn` 后插入：

```python
        await chat_service_with_memory.run_turn("session-123", user_message)

        # 记忆提取已异步化：等后台 worker 消费完再断言落库效果
        await get_memory_extraction_queue().drain()
```

（`test_chat_service_skips_short_conversations` 断言 `not store.called`，短对话提取为空，无需 drain。）

- [ ] **Step 3: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_chat_service_memory.py backend/tests/unit/test_async_extractor.py -v`
Expected: PASS — 含新 drain 后断言成立

- [ ] **Step 4: Commit**

```bash
git add backend/application/services/chat_service.py backend/tests/unit/test_chat_service_memory.py
git commit -m "feat: hex 记忆提取改为后台队列 submit（不阻塞响应）"
```

---

### Task 3: legacy `_extract_legacy_chat_memory` → `queue.submit`（适配 test_legacy_memory_extraction.py）

**Files:**
- Modify: `backend/api/legacy_routes.py`（`_extract_legacy_chat_memory`，~line 511-560）
- Modify: `backend/tests/integration/test_legacy_memory_extraction.py`（加 drain helper + 2 处调用）
- Test: `backend/tests/integration/test_legacy_memory_extraction.py`

**Interfaces:**
- Consumes: `ExtractionRequest` / `get_memory_extraction_queue()`（Task 1）
- Produces: legacy 路径保留 autoMemory 检查 + adapter/extractor 装配，末尾 submit 不 await

- [ ] **Step 1: 改 legacy 路径为 submit**

`backend/api/legacy_routes.py`，`_extract_legacy_chat_memory` 函数体（docstring 同步更新为"装配廉价部分 + 投递后台队列"），替换调用段：

```python
        from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
        from backend.adapters.out.memory.adapter import MemoryAdapter
        from backend.memory.async_extractor import (
            ExtractionRequest,
            get_memory_extraction_queue,
        )
        from backend.memory.extractor import MemoryExtractor

        # 记忆提取异步化：廉价装配（读设置/建 adapter）仍在本函数内完成，
        # 仅把耗时的 LLM 提取投递到后台队列，不阻塞流式请求收尾。
        get_memory_extraction_queue().submit(
            ExtractionRequest(
                memory_port=MemoryAdapter(get_memory_manager()),
                extractor=MemoryExtractor(llm_client=HttpxLLMAdapter()),
                user_text=user_text,
                assistant_text=assistant_text,
                session_id=session_id,
                enabled=True,
            )
        )
```

删除原 `from backend.application.services.chat_service import extract_and_store_memory` 与 `await extract_and_store_memory(...)` 调用。

- [ ] **Step 2: 适配 test_legacy_memory_extraction.py**

模块级追加 drain helper（`_run_chat_stream` 之后）：

```python
async def _await_extraction() -> None:
    """等后台记忆提取 worker 消费完队列（提取已异步化）。"""
    from backend.memory.async_extractor import get_memory_extraction_queue

    await get_memory_extraction_queue().drain(timeout=5.0)
```

`test_legacy_chat_stream_extracts_memory_after_assistant_persisted` 在 `attach_text = await _run_chat_stream(...)` 后追加：

```python
    await _await_extraction()
```

`test_legacy_chat_stream_extraction_failure_does_not_break_stream` 同样在 `_run_chat_stream` 后追加：

```python
    await _await_extraction()
```

（`auto_memory_disabled` 与 `assistant_persist_failure` 两测试不产生 submit，无需 drain。）

- [ ] **Step 3: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_legacy_memory_extraction.py -v`
Expected: PASS — 4/4 绿

- [ ] **Step 4: Commit**

```bash
git add backend/api/legacy_routes.py backend/tests/integration/test_legacy_memory_extraction.py
git commit -m "feat: legacy 记忆提取改为后台队列 submit（不阻塞流式收尾）"
```

---

### Task 4: main.py lifespan 装配 + 全量回归

**Files:**
- Modify: `backend/main.py`（lifespan 启动段 ~line 166 后 + 关闭段 ~line 305 前）
- Test: 全量回归

**Interfaces:**
- Consumes: `get_memory_extraction_queue()` / `.start()` / `.drain()` / `.stop()`（Task 1）

- [ ] **Step 1: lifespan 启动 worker**

`backend/main.py`，在 stream sweeper 初始化（`logger.info("ChatStreamRegistry 已初始化...")`，~line 165）之后追加：

```python
    # 记忆提取异步化：后台单 worker 消费提取队列，不阻塞聊天响应
    from backend.memory.async_extractor import get_memory_extraction_queue

    get_memory_extraction_queue().start()
    logger.info("MemoryExtractionQueue 已启动（记忆提取后台 worker）")
```

- [ ] **Step 2: lifespan 关闭时优雅排空**

`backend/main.py` 关闭段（`await app.state.wake_scheduler.stop()`，~line 299 之后）追加：

```python
    # 记忆提取：优雅排空在途提取（best-effort，超时 5s 丢弃）
    try:
        from backend.memory.async_extractor import get_memory_extraction_queue

        await get_memory_extraction_queue().drain(timeout=5.0)
        get_memory_extraction_queue().stop()
    except Exception as exc:  # noqa: BLE001 — shutdown must not raise
        logger.warning("MemoryExtractionQueue shutdown failed: %s", exc)
```

- [ ] **Step 3: 全量后端测试 + ruff**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests -q
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/memory/async_extractor.py backend/application/services/chat_service.py backend/api/legacy_routes.py backend/main.py backend/tests/unit/test_async_extractor.py backend/tests/unit/test_chat_service_memory.py backend/tests/integration/test_legacy_memory_extraction.py backend/tests/conftest.py
```
Expected: pytest 全量 PASS，ruff 0 errors

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: lifespan 启动/关闭记忆提取后台 worker"
```

---

## Self-Review

**Spec 覆盖对照：**

| Spec 要求 | 对应任务 |
|---|---|
| 新增 MemoryExtractionQueue（submit/worker/drain/单例） | Task 1 |
| 单 worker 串行 + 顺序保证 | Task 1（`test_single_worker_serial` / `test_submits_processed_in_order`） |
| 非阻塞 submit（不等结果，区别于 FileMutationQueue） | Task 1（`test_submit_is_non_blocking`） |
| 错误处理三层（worker 外圈 / 前置过滤 / 计数器） | Task 1（`test_worker_survives_single_failure` / `test_submit_filters_disabled_and_none` / failed/skipped 属性） |
| hex run_turn step 7 → submit | Task 2 |
| legacy `_extract_legacy_chat_memory` → submit（保留 autoMemory 检查 + 装配） | Task 3 |
| span `memory.stored_facts` 移除 | Task 2 |
| 生命周期：lifespan 启动/关闭 drain(5s) | Task 4 |
| 测试：新单测 + 现有 2 文件适配 | Task 1/2/3 |
| `extract_and_store_memory` 单测不动 | Task 1（worker 懒导入，`test_chat_service_snapshot.py` 不改） |

**占位符检查：** 无 TBD/TODO；所有代码块含完整实现。

**类型一致性：** `ExtractionRequest` 字段 `(memory_port, extractor, user_text, assistant_text, session_id, enabled)` 在 Task 1 定义、Task 2/3 构造、worker `_process` 透传，全程一致。方法名 `submit/start/stop/drain/pending` 与 `.completed/.failed/.skipped` 属性在 Task 1 定义、Task 2/3/4 引用，一致。
