# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (List[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
"""
API 路由定义
"""

from __future__ import annotations

import asyncio
import contextlib
import json

# I5: 流式视觉延迟 — DONE 事件的 content 拆成 chunk 逐个入队,
# 让前端能逐字渲染 (避免 LLM 一次返回完整字符串时 "砰一下" 全显示)。
# 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls (大改),
# 先用这个 producer 端的 fake stream 解决 90% 的视觉体验。
_STREAMING_CHUNK_SIZE = 6
_STREAMING_CHUNK_DELAY_S = 0.04
import logging
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.chat.compaction import (
    estimate_messages_tokens,
)
from backend.memory import get_memory_manager
from backend.memory.summary import (
    list_summaries_for_session as _list_summaries_for_session,
)


def _resolve_effective_window(  # noqa: PLR0911 — Task 5 priority cascade, each branch is a distinct user-facing mode
    model_id: Optional[str] = None,
    max_context: Optional[int] = None,
    request_endpoint_id: Optional[str] = None,
    auto_context: Optional[bool] = None,
) -> Optional[int]:
    """Task 5: Resolve effective context window from model catalog.

    Priority for ``endpoint_id``: request > persisted settings > None.
    Behaviour by ``auto_context`` flag (after catalog resolve):

    - ``auto_context=True``  → resolve from catalog; ``max_context``, if
      set, is applied as a safety upper bound (``min(catalog, max)``).
      This is the path that lets the UI's ``autoContext`` switch actually
      turn on catalog-driven window sizing.
    - ``auto_context=False`` → fixed cap at ``max_context`` (user pinned
      a value). Catalog caps still apply via effective_window.
    - ``auto_context=None``  → resolve from catalog (the default for
      callers that do not yet pass the field), 4096 default cap.

    Returns ``max_context`` if the catalog cannot be resolved, else
    ``None`` so callers can decide how to fall back.
    """
    try:
        from backend.data.database import get_database
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository
        from backend.model_catalog.context import effective_window
        from backend.model_catalog.repository import CatalogRepository
        from backend.model_catalog.schemas import EndpointKey

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return max_context if max_context else None
        settings = to_camel(raw)
        endpoints = settings.get("endpoints") or []
        if not isinstance(endpoints, list):
            return max_context if max_context else None

        # Priority: request endpoint_id > persisted settings
        endpoint_id = None
        if request_endpoint_id:
            # Verify the request endpoint_id exists in the endpoints list
            ep = next(
                (e for e in endpoints if isinstance(e, dict) and e.get("id") == request_endpoint_id),
                None,
            )
            if ep is not None:
                endpoint_id = request_endpoint_id

        if not endpoint_id:
            # Fallback to persisted settings
            selections = settings.get("modelSelections") or {}
            chat_sel = selections.get("chatModel") if isinstance(selections, dict) else None
            if isinstance(chat_sel, dict) and chat_sel.get("endpointId"):
                ep_id = chat_sel["endpointId"]
                ep = next(
                    (e for e in endpoints if isinstance(e, dict) and e.get("id") == ep_id),
                    None,
                )
                if ep is not None:
                    endpoint_id = ep_id

        if not endpoint_id or not model_id:
            return max_context if max_context else None

        repo = CatalogRepository(get_database())
        resolved = repo.resolve(EndpointKey(endpoint_id=endpoint_id, model_id=model_id))
        # auto_context=True (UI toggle on): catalog-driven window with
        # max_context as a safety upper bound. This is the only branch
        # where the UI's autoContext switch actually reaches catalog
        # resolution — without it, the previous logic made max_context
        # always win and the toggle was inert.
        if auto_context is True:
            # effective_window(automatic=True) ignores ``fixed`` per the
            # schema contract, so the natural catalog window is returned
            # first and only then clamped to max_context. 4096 is a
            # stand-in positive int — its value is discarded.
            window = effective_window(
                resolved.limits, automatic=True, fixed=4096,
            )
            if max_context:
                window = min(window, max_context)
            return window
        # auto_context=False: user explicitly pinned a value, treat as cap.
        if auto_context is False and max_context:
            return effective_window(
                resolved.limits, automatic=False, fixed=max_context,
            )
        # auto_context=None (or False without max_context): resolve from
        # catalog, 4096 default ceiling.
        return effective_window(
            resolved.limits, automatic=True, fixed=4096,
        )
    except Exception:
        return max_context if max_context else None


def _check_request_within_window(
    messages: Sequence[Dict[str, Any]],
    effective_window: Optional[int],
) -> None:
    """Brief line 16: explicit reject when required content overshoots window.

    The history was already truncated to ``max(0, effective_window - reserve)``,
    so this guard only fires when system / attachments / trailing_system /
    current user input alone exceed the resolved window (e.g., a 1 MB
    attachment + a long system prompt against a 4K-window model). Without
    this check the producer would silently send an over-budget request that
    the upstream LLM truncates or errors on — this gives the caller a
    deterministic 400 instead.

    No-op when the catalog has not resolved a window (``effective_window``
    is None or non-positive) so callers without catalog data keep the legacy
    behaviour.
    """
    if effective_window is None or effective_window <= 0:
        return
    total = estimate_messages_tokens(messages)
    if total > effective_window:
        raise HTTPException(
            status_code=400,
            detail=(
                f"required content (system + history + attachments + current "
                f"input) ~{total} tokens exceeds resolved context window "
                f"({effective_window} tokens); reduce input length, drop "
                f"attachments, or pick a larger-context model"
            ),
        )



logger = logging.getLogger(__name__)

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由 with_db_lock 闭包解析
    _SQLITE_LOCK,
    make_with_db_lock,
)


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    D3 同款（镜像 orch_routes）：make_with_db_lock 把 wrapper 的
    __globals__ 重绑到本模块（FastAPI 字符串注解须在本模块解析，body
    模型如 MemorySaveRequest），_SQLITE_LOCK 经 import 共享同一对象，
    与 legacy_routes 的锁语义一致。
    """
    return make_with_db_lock(globals())(func)


_MEMORY_LIST_MAX_PAGE_SIZE = 100
_MEMORY_LIST_MAX_FETCH = 1000
_MEMORY_LIST_MAX_PAGE = _MEMORY_LIST_MAX_FETCH // _MEMORY_LIST_MAX_PAGE_SIZE

router = APIRouter()

# ==================== 记忆 list/summaries API（C1 第一刀第二片）=====
@router.get("/memory/list")
@with_db_lock
def list_memories(
    page: int = 1,
    page_size: int = 20,
    offset: Optional[int] = None,
    type: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """获取记忆列表（带 layer / source / 分页 envelope）。

    Task 2 起:
    - 分页参数 clamp 到合法范围 (``page >= 1``, ``page_size`` in ``[1, 100]``)。
    - 返回 envelope ``{items, total, page, page_size, layer, source_breakdown}``,
      替代旧实现返回裸 list 的契约。
    - ``type`` 可为 ``None`` / ``''`` / ``'all'`` → 合并 episodic + semantic
      (其他 type 仍走对应层)。
    - 每条记录带 ``source`` (``'episodic'`` / ``'semantic'``) 与 ``layer``
      字段,与 ``MemoryManager.search_memories`` 对齐。

    批次三 step 6 起 (spec §4.3 line 150):
    - ``type=None`` / ``'all'`` / ``''`` 现在合并**四层**: working +
      session_summary + episodic + semantic（不再只返回 episodic + semantic）。
    - 新增 ``offset`` query 参数：调用方可直接传 offset 游标,不必先算 page。
    - 新增 ``session_id`` query 参数: 按 session 隔离列表,呼应 step 5 的
      session 隔离不变量。
    - ``source_breakdown`` 输出新增 ``working`` 和 ``session_summary`` 计数。
    """
    try:
        # 1. 输入 clamp
        safe_page = max(
            1,
            min(
                _MEMORY_LIST_MAX_PAGE,
                int(page) if page is not None else 1,
            ),
        )
        safe_page_size = max(
            1,
            min(
                _MEMORY_LIST_MAX_PAGE_SIZE,
                int(page_size) if page_size is not None else 20,
            ),
        )
        # offset 默认从 page 派生;调用方显式传 offset 时优先使用。
        safe_offset = (
            max(0, int(offset))
            if offset is not None
            else (safe_page - 1) * safe_page_size
        )
        fetch_limit = min(
            _MEMORY_LIST_MAX_FETCH,
            safe_offset + safe_page + safe_page_size,
        )
        normalized_type = type if type and type not in ("", "all") else None

        mm = get_memory_manager()
        # 2. 取数 (按 type 路由)
        if normalized_type == "episodic":
            episodic_items = mm.episodic.get_recent(
                limit=fetch_limit, session_id=session_id
            )
            items = _enrich_memory_records(
                episodic_items, layer="episodic", source="episodic"
            )
            # step 5: session_id 给定时,total 必须按会话统计,否则分页 envelope
            # 会把其它会话的内存以 total 形式泄漏给 UI
            total = mm.episodic.count(session_id=session_id)
            source_breakdown = {
                "working": 0,
                "session_summary": 0,
                "episodic": len(items),
                "semantic": 0,
            }
        elif normalized_type == "semantic":
            semantic_items = mm.semantic.get_recent(
                limit=fetch_limit, session_id=session_id
            )
            items = _enrich_memory_records(
                semantic_items, layer="semantic", source="semantic"
            )
            total = mm.semantic.count(session_id=session_id)
            source_breakdown = {
                "working": 0,
                "session_summary": 0,
                "episodic": 0,
                "semantic": len(items),
            }
        elif normalized_type == "working":
            working_items = mm.working.get_context(
                session_id=session_id, limit=fetch_limit
            ) if session_id else list(mm.working.messages)[-fetch_limit:]
            items = _enrich_working_records(working_items, session_id=session_id)
            total = len(items)
            source_breakdown = {
                "working": len(items),
                "session_summary": 0,
                "episodic": 0,
                "semantic": 0,
            }
        elif normalized_type == "session_summary":
            # step 6 兼容:旧 MemoryManager 没有 summary_store → 返空 envelope,不 500
            if mm.summary_store is None or not session_id:
                items = []
                total = 0
            else:
                summaries = _list_summaries_for_session(
                    db=mm.summary_store.db,
                    session_id=session_id,
                    limit=fetch_limit,
                )
                items = _enrich_summary_records(summaries)
                total = len(summaries)
            source_breakdown = {
                "working": 0,
                "session_summary": total,
                "episodic": 0,
                "semantic": 0,
            }
        else:
            # 'all' / '' / None → 合并四层: working + session_summary +
            # episodic + semantic,按 created_at 倒序
            episodic_items = mm.episodic.get_recent(
                limit=fetch_limit, session_id=session_id
            )
            semantic_items = mm.semantic.get_recent(
                limit=fetch_limit, session_id=session_id
            )

            # Working memory: 当 session_id 给定时取该会话;否则取全局最后 N 条
            if session_id:
                working_items = mm.working.get_context(
                    session_id=session_id, limit=fetch_limit
                )
            else:
                # 全局视图: 跨会话聚合(粗粒度,按 timestamp 排序)
                working_items = list(mm.working.messages)[-fetch_limit:]

            # Session summaries: 只在 session_id 给定时注入
            # (不输出"全 session 摘要",以防跨 session 串味)
            summaries = []
            if session_id and mm.summary_store is not None:
                summaries = _list_summaries_for_session(
                    db=mm.summary_store.db,
                    session_id=session_id,
                    limit=fetch_limit,
                )

            merged: List[Dict] = []
            merged.extend(
                _enrich_memory_records(episodic_items, layer="episodic", source="episodic")
            )
            merged.extend(
                _enrich_memory_records(semantic_items, layer="semantic", source="semantic")
            )
            merged.extend(_enrich_working_records(working_items, session_id=session_id))
            merged.extend(_enrich_summary_records(summaries))
            # 按 created_at_ms / timestamp 倒序
            merged.sort(
                key=lambda x: x.get("created_at_ms", x.get("timestamp_ms", 0)),
                reverse=True,
            )
            items = merged
            try:
                # step 5: total 必须按 session 隔离,否则 envelope 会把其它
                # 会话的条目数泄漏给当前会话的 UI
                total = (
                    mm.episodic.count(session_id=session_id)
                    + mm.semantic.count(session_id=session_id)
                    + len(working_items)
                    + len(summaries)
                )
            except Exception:
                total = len(items)
            source_breakdown = {
                "working": len(working_items),
                "session_summary": len(summaries),
                "episodic": len(episodic_items),
                "semantic": len(semantic_items),
            }

        # 3. 分页 slice
        page_items = items[safe_offset : safe_offset + safe_page_size]

        # 4. Envelope
        return {
            "items": page_items,
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "offset": safe_offset,
            "layer": normalized_type or "all",
            "source_breakdown": source_breakdown,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _enrich_memory_records(
    records: List[Dict[str, Any]], layer: str, source: str
) -> List[Dict[str, Any]]:
    """给每条记忆记录补 ``source`` / ``layer`` / ``created_at_ms``。

    字段约定:
    - ``id`` / ``content`` / ``memory_type`` / ``source`` / ``session_id``
      / ``importance`` / ``created_at_ms`` / ``summary``
    - ``created_at`` 字段若存在,映射成 ``created_at_ms``(毫秒)。

    ``source`` 强制覆盖(不用 setdefault):DB 里 ``source`` 列存的是
    'auto'/'manual'/'review' 之类的"写入来源",而这里我们要的是"层来源"
    (episodic/semantic)。两者语义不同,务必区分,UI 按这个字段决定走
    哪个标签样式。
    """
    enriched: List[Dict[str, Any]] = []
    for raw in records or []:
        item = dict(raw)
        item["source"] = source  # 强制覆盖,与 DB 列 source 解耦
        item["layer"] = layer
        # created_at (秒) → created_at_ms (毫秒)
        if "created_at_ms" not in item and "created_at" in item:
            ts = item["created_at"]
            # 数据库列存的就是毫秒（int(time.time() * 1000)），原样复制
            with contextlib.suppress(TypeError, ValueError):
                item["created_at_ms"] = int(ts)
        enriched.append(item)
    return enriched


def _enrich_working_records(
    messages: List[Dict[str, Any]], session_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """把工作记忆消息序列化成 ``/memory/list`` 的统一记录格式。

    工作记忆是 in-memory deque,不是 DB 行,所以这里手填
    ``source='working'`` / ``layer='working'`` 让 UI 走对应的徽章样式。
    ``created_at_ms`` 用 ``timestamp * 1000``(秒→毫秒,spec §4.4 step 1)。
    """
    enriched: List[Dict[str, Any]] = []
    for msg in messages or []:
        item = dict(msg)
        sid = item.get("session_id", session_id or "")
        seq = item.get("seq", 0)
        item["id"] = item.get("id") or f"wm:{sid}:{seq}"
        item["source"] = "working"
        item["layer"] = "working"
        item["memory_type"] = "working"
        ts = item.get("timestamp", 0)
        try:
            item["created_at_ms"] = int(float(ts) * 1000)
        except (TypeError, ValueError):
            item["created_at_ms"] = 0
        item["timestamp_ms"] = item["created_at_ms"]
        item["content"] = item.get("content", "")
        item["importance"] = item.get("importance", 0)
        enriched.append(item)
    return enriched


def _enrich_summary_records(
    summaries: List[Any],
) -> List[Dict[str, Any]]:
    """把 :class:`SessionSummary` 行转成 ``/memory/list`` 的统一格式。

    ``source='session_summary'`` / ``layer='session_summary'`` 区分于持久层
    (episodic/semantic)。``created_at_ms`` 已经是 spec §4.4 规范的毫秒,
    直接透传。
    """
    enriched: List[Dict[str, Any]] = []
    for s in summaries or []:
        enriched.append(
            {
                "id": s.id,
                "source": "session_summary",
                "layer": "session_summary",
                "memory_type": "session_summary",
                "session_id": s.session_id,
                "source_turn_id": s.source_turn_id,
                "content": s.content,
                "status": s.status,
                "error_message": s.error_message,
                "created_at_ms": s.created_at_ms,
                "updated_at_ms": s.updated_at_ms,
                "importance": 0,
                "summary": (s.content or "")[:100],
            }
        )
    return enriched


@router.get("/memory/summaries")
@with_db_lock
def list_session_summaries(
    session_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """按 session 列出 session_summaries 行(批次三 step 6,spec §4.3)。

    跨 session 串味是 step 5 严令禁止的,所以 ``session_id`` **必填**:
    不存在"全部 session 的摘要列表"这种视图。漏传 session_id 直接
    400,而不是默认某 session。

    包含 READY/FAILED/PENDING 三种 status 行,这样 UI 能正确显示
    "上一次生成失败"等诊断,而不会把失败伪装成 READY。
    """
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="session_id is required for /memory/summaries "
            "(spec §4.3 step 5 forbids cross-session reads)",
        )

    try:
        safe_page = max(1, int(page))
        safe_page_size = max(
            1, min(_MEMORY_LIST_MAX_PAGE_SIZE, int(page_size))
        )
        safe_offset = (safe_page - 1) * safe_page_size

        mm = get_memory_manager()
        if mm.summary_store is None:
            # 没有 store (旧版 MemoryManager) 就直接返空,避免 500。
            return {
                "session_id": session_id,
                "items": [],
                "total": 0,
                "page": safe_page,
                "page_size": safe_page_size,
                "offset": safe_offset,
            }

        # 用 session_id 强过滤(防 step 5 跨 session 串味)
        all_rows = _list_summaries_for_session(
            db=mm.summary_store.db,
            session_id=session_id,
            limit=_MEMORY_LIST_MAX_FETCH,
        )
        total = len(all_rows)
        page_items = all_rows[safe_offset : safe_offset + safe_page_size]

        return {
            "session_id": session_id,
            "items": _enrich_summary_records(page_items),
            "total": total,
            "page": safe_page,
            "page_size": safe_page_size,
            "offset": safe_offset,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Wave 2 P1-4 (2026-08-14): 编排 run 读取/resume/计划更新端点挂载。
# orch_routes 用独立 APIRouter(prefix="/orch")，经 include_router 并入
# legacy_router → main.py 挂载后最终前缀 /api/v1/orch。


# ==================== 记忆可追溯性 API (Gap E / Task 5) ====================


def _get_memory_port(request: Request):
    """返回 MemoryAdapter（MemoryPort 实现）。

    生产路径：``main.py`` lifespan 把 adapter 挂在 ``app.state.memory_port``。
    测试路径（不走 lifespan）：惰性构造一个绑定当前 MemoryManager 的
    adapter —— conftest 已把 MemoryManager 重置到临时 DB，因此查询
    打到测试库。
    """
    port = getattr(request.app.state, "memory_port", None)
    if port is not None:
        return port
    from backend.adapters.out.memory.adapter import MemoryAdapter

    return MemoryAdapter(get_memory_manager())


@router.get("/memory/by-turn/{turn_id}")
async def get_memories_by_turn(turn_id: str, request: Request):
    """按来源 turn 查询记忆（可追溯性：从记忆点击跳回产生它的轮次）。"""
    memory_port = _get_memory_port(request)
    memories = await memory_port.find_by_turn(turn_id)
    return {"memories": list(memories)}


@router.get("/memory/summary/{session_id}")
async def get_session_summary(session_id: str, request: Request):
    """按会话聚合 task_summary 记忆（会话摘要 Tab）。"""
    memory_port = _get_memory_port(request)
    summaries = await memory_port.find_by_category_and_session("task_summary", session_id)
    return {"summaries": list(summaries), "session_id": session_id}


# ==================== 记忆 SSE 流 (Task 6) ====================


@router.get("/memory/events")
async def memory_events(request: Request):
    """SSE 流：订阅 ``memory_written`` 生命周期事件 (Task 6)。

    每个连接持有独立的 ``asyncio.Queue(maxsize=100)``；进程内
    HookRegistry 触发 ``memory_written`` 时把事件序列化后推给连接。
    15s 无事件时发心跳 ``: heartbeat`` 保持连接。客户端断开
    (``request.is_disconnected()``) 或请求取消时在 ``finally`` 注销
    监听器，避免 per-connection 闭包泄漏。

    Electron 主进程 (``electron/main.ts``) 通过 EventSource 消费此流，
    再通过 IPC ``sage:memory:event`` 转发给渲染进程。
    """
    from backend.memory.hooks import HookRegistry
    from backend.memory.lifecycle import MemoryWriteEvent

    hooks: HookRegistry = getattr(request.app.state, "hooks", None)
    if hooks is None:
        raise HTTPException(
            status_code=503,
            detail="memory hook registry not initialized",
        )

    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    def on_memory_written(event: object) -> None:
        """Hook 监听器（同步）：入队；队列满则丢弃并告警，绝不上抛。"""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("memory events queue full, dropping event")

    hooks.on("memory_written", on_memory_written)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:  # noqa: UP041 — Py3.10 asyncio.TimeoutError
                    yield ": heartbeat\n\n"
                    continue
                if not isinstance(event, MemoryWriteEvent):
                    continue
                payload = json.dumps(
                    {
                        "memory_id": event.memory_id,
                        "content": event.content,
                        "memory_type": event.memory_type,
                        "memory_category": event.memory_category,
                        "session_id": event.session_id,
                        "turn_id": event.turn_id,
                        "timestamp": event.timestamp.isoformat(),
                    },
                    ensure_ascii=False,
                )
                yield f"data: {payload}\n\n"
        finally:
            hooks.off("memory_written", on_memory_written)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

