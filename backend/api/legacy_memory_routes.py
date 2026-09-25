# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (List[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
"""
API 路由定义
"""

from __future__ import annotations

import hashlib

# I5: 流式视觉延迟 — DONE 事件的 content 拆成 chunk 逐个入队,
# 让前端能逐字渲染 (避免 LLM 一次返回完整字符串时 "砰一下" 全显示)。
# 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls (大改),
# 先用这个 producer 端的 fake stream 解决 90% 的视觉体验。
_STREAMING_CHUNK_SIZE = 6
_STREAMING_CHUNK_DELAY_S = 0.04
import logging
import os
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.chat.compaction import (
    estimate_messages_tokens,
)
from backend.data.database import get_database
from backend.memory import get_memory_manager


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


router = APIRouter()

# ==================== 记忆核心 API（C1 第一刀，自 legacy_routes.py 迁出）=====

# ==================== 记忆 API（C1 第一刀，自 legacy_routes.py 尾部迁出）=====
# 路径与前缀保持不变（router 无 prefix，经 legacy_router include 后仍为
# /api/v1/memory/*）——纯物理拆分，零行为变更。依赖 via legacy_router 的
# include_router 链挂载（main.py 不直接感知本文件）。
# ==================== 记忆 API ====================

# get_memory_manager 从 backend.memory 导入（全局单例）


class MemorySearchRequest(BaseModel):
    query: str
    memory_type: Optional[str] = None

    limit: int = 20


class MemorySaveRequest(BaseModel):
    content: str = Field(min_length=1)
    memory_type: str = "episodic"
    importance: int = Field(default=5, ge=1, le=10)
    tags: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None
    # P1 作用域轴: None/'auto' → 按会话绑定自动判定; 可显式 'user'/'project'/'global'
    scope: Optional[str] = None
    # P3: true 时走 Mem0 风格冲突消解写入 (NOOP/UPDATE/ADD), 响应带 op 字段
    conflict_check: bool = False


class MemoryDeleteRequest(BaseModel):
    id: str


# ---- 对标 S2（2026-09-13）：记忆写入台账 / 撤销 / 用户画像 CRUD ---------


class MemoryUndoWriteRequest(BaseModel):
    session_id: str
    id: str


class UserProfileCreateRequest(BaseModel):
    content: str
    category: str = "preference"
    importance: int = 5


class UserProfileUpdateRequest(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[int] = None


class ProjectProfileCreateRequest(BaseModel):
    content: str
    category: str = "convention"
    importance: int = 5
    # 归属二选一：显式 project_key 优先，否则从 session_id 解析工作区绑定。
    project_key: Optional[str] = None
    session_id: Optional[str] = None


@router.get("/memory/recent-writes")
def list_recent_memory_writes(session_id: str, after_seq: int = 0, limit: int = 20):
    """本会话最近的记忆写入（对标 ChatGPT "Memory updated" 提示）。

    进程内台账（``backend.memory.write_ledger``），``after_seq`` 为游标：
    前端记住上次返回的 ``latest_seq``，下次只取增量。台账不可用时返回空。
    """
    try:
        from backend.memory.write_ledger import get_write_ledger

        ledger = get_write_ledger()
        items = ledger.list_since(session_id, after_seq=after_seq, limit=min(max(limit, 1), 50))
        return {
            "items": [r.to_dict() for r in items],
            "latest_seq": ledger.latest_seq(session_id),
        }
    except Exception as exc:  # noqa: BLE001 — 增强信息，绝不 500
        logger.debug(f"recent memory writes skipped: {exc}")
        return {"items": [], "latest_seq": int(after_seq or 0)}


@router.post("/memory/undo-write")
@with_db_lock
def undo_memory_write(data: MemoryUndoWriteRequest):
    """撤销一次刚刚发生的记忆写入（按台账 kind 路由到记忆层 / 用户画像 / 项目画像）。"""
    from backend.memory.write_ledger import (
        KIND_PROFILE,
        KIND_PROJECT_PROFILE,
        get_write_ledger,
    )

    ledger = get_write_ledger()
    rec = ledger.find(data.session_id, data.id)
    deleted = False
    try:
        if rec is not None and rec.kind == KIND_PROJECT_PROFILE:
            from backend.memory.project_profile import get_project_profile

            deleted = get_project_profile().delete(data.id)
        elif rec is not None and rec.kind == KIND_PROFILE:
            from backend.memory.user_profile import get_user_profile

            deleted = get_user_profile().delete(data.id)
        else:
            mm = get_memory_manager()
            for mtype in ("episodic", "semantic"):
                if mm.delete_memory(data.id, mtype):
                    deleted = True
                    break
            if not deleted and rec is None:
                # 台账过期但可能是画像条目：兜底尝试画像库
                from backend.memory.user_profile import get_user_profile

                deleted = get_user_profile().delete(data.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在或已被删除")
    ledger.forget(data.session_id, data.id)
    return {"status": "ok", "id": data.id, "kind": rec.kind if rec else "memory"}


@router.get("/memory/profile")
def list_user_profile():
    """用户画像列表（"关于我"卡片数据源）。"""
    try:
        from backend.memory.user_profile import VALID_CATEGORIES, get_user_profile

        store = get_user_profile()
        return {
            "items": store.list(),
            "categories": list(VALID_CATEGORIES),
            "snapshot": store.get_snapshot(),
            "char_limit": store.char_limit,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/profile")
@with_db_lock
def create_user_profile(data: UserProfileCreateRequest):
    """新增画像条目；写入后立即刷新冻结快照，让下一轮对话生效。"""
    try:
        from backend.memory.user_profile import get_user_profile

        store = get_user_profile()
        pid = store.add(data.content, category=data.category, importance=data.importance)
        if not pid:
            raise HTTPException(status_code=409, detail="内容为空、与现有画像重复或被安全扫描拦截")
        store.invalidate()
        item = next((e for e in store.list() if e["id"] == pid), None)
        return {"status": "ok", "item": item}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/memory/profile/{profile_id}")
@with_db_lock
def update_user_profile(profile_id: str, data: UserProfileUpdateRequest):
    """编辑画像条目：删旧建新（复用 add 的去重 / 安全扫描 / 钳制）。"""
    try:
        from backend.memory.user_profile import get_user_profile

        store = get_user_profile()
        old = next((e for e in store.list() if e["id"] == profile_id), None)
        if old is None:
            raise HTTPException(status_code=404, detail="画像条目不存在")
        content = (data.content if data.content is not None else old["content"]).strip()
        category = data.category or old["category"]
        importance = data.importance if data.importance is not None else old.get("importance", 5)
        if not content:
            raise HTTPException(status_code=400, detail="内容不能为空")
        store.delete(profile_id)
        pid = store.add(content, category=category, importance=importance)
        if not pid:
            # 新内容被拒（重复/安全）→ 回滚旧条目
            store.add(old["content"], category=old["category"], importance=old.get("importance", 5))
            store.invalidate()
            raise HTTPException(status_code=409, detail="新内容与现有画像重复或被安全扫描拦截")
        store.invalidate()
        item = next((e for e in store.list() if e["id"] == pid), None)
        return {"status": "ok", "item": item}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memory/profile/{profile_id}")
@with_db_lock
def delete_user_profile(profile_id: str):
    try:
        from backend.memory.user_profile import get_user_profile

        if not get_user_profile().delete(profile_id):
            raise HTTPException(status_code=404, detail="画像条目不存在")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- P2 项目画像（项目级 MEMORY.md）--------------------------------------


def _resolve_profile_project_key(
    project_key: Optional[str], session_id: Optional[str]
) -> Optional[str]:
    """显式 project_key 优先；否则从会话的工作区绑定解析。解析不到返回 None。"""
    key = (project_key or "").strip()
    if key:
        return key
    if not session_id:
        return None
    from backend.memory import scope as memory_scope

    return memory_scope.resolve_session_project_key(get_database(), session_id)


@router.get("/memory/project-profile")
def list_project_profile(
    project_key: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """项目画像列表。归属解析不到时返回空列表（未绑定会话无项目画像）。"""
    try:
        from backend.memory.project_profile import (
            VALID_CATEGORIES,
            get_project_profile,
        )

        key = _resolve_profile_project_key(project_key, session_id)
        store = get_project_profile()
        return {
            "project_key": key or "",
            "items": store.list(key) if key else [],
            "categories": list(VALID_CATEGORIES),
            "snapshot": store.get_snapshot(key) if key else "",
            "char_limit": store.char_limit,
            "projects": store.projects(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/project-profile")
@with_db_lock
def create_project_profile(data: ProjectProfileCreateRequest):
    """新增项目画像条目；写入后立即刷新该项目的冻结快照。"""
    try:
        from backend.memory.project_profile import get_project_profile

        key = _resolve_profile_project_key(data.project_key, data.session_id)
        if not key:
            raise HTTPException(
                status_code=400,
                detail="无法确定项目归属：请提供 project_key 或绑定工作区的 session_id",
            )
        store = get_project_profile()
        pid = store.add(
            key,
            data.content,
            category=data.category,
            importance=data.importance,
        )
        if not pid:
            raise HTTPException(status_code=409, detail="内容为空、与现有画像重复或被安全扫描拦截")
        store.invalidate(key)
        item = next((e for e in store.list(key) if e["id"] == pid), None)
        return {"status": "ok", "item": item, "project_key": key}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memory/project-profile/{profile_id}")
@with_db_lock
def delete_project_profile(profile_id: str):
    try:
        from backend.memory.project_profile import get_project_profile

        if not get_project_profile().delete(profile_id):
            raise HTTPException(status_code=404, detail="项目画像条目不存在")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/search")
@with_db_lock
def search_memory(
    query: str,
    limit: int = 20,
    type: Optional[str] = None,
    scope: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """搜索记忆。

    P1 作用域轴: ``scope`` in ('user'|'project'|'global') 时按作用域跨会话
    检索（'project' 需带 session_id 以解析当前项目目录）；缺省维持
    会话内旧行为。
    """
    if type not in (None, "", "working", "episodic", "semantic"):
        raise HTTPException(status_code=422, detail="不支持的记忆类型")
    try:
        mm = get_memory_manager()
        return mm.search_memories(
            query=query,
            memory_type=type or None,
            limit=max(1, min(limit, 100)),
            scope=scope,
            session_id=session_id,
        )
    except HTTPException:
        raise
    except Exception:
        # 脱敏:不泄露用户原始查询(查询进入 URL 后会出现在错误日志里)
        raise HTTPException(status_code=500, detail="记忆搜索失败,请查看后端日志")


@router.get("/memory/diagnostics")
def memory_diagnostics():
    """Return redacted runtime evidence for diagnosing an empty memory list."""
    from pathlib import Path

    db = get_memory_manager().episodic.db
    raw_path = str(getattr(db, "db_path", ""))
    path = Path(raw_path)
    try:
        stat = path.stat()
        size_bytes = stat.st_size
        exists = True
    except OSError:
        size_bytes = 0
        exists = False
    path_fingerprint = hashlib.sha256(raw_path.encode("utf-8")).hexdigest()[:16]
    return {
        "pid": os.getpid(),
        "build_id": os.environ.get("SAGE_BUILD_ID", "dev-build"),
        "db": {
            "basename": path.name,
            "exists": exists,
            "size_bytes": size_bytes,
            "path_fingerprint": path_fingerprint,
            "source": "explicit_env" if os.environ.get("SAGE_DB_PATH") else "default",
        },
    }


@router.post("/memory/save")
@with_db_lock
def save_memory(data: MemorySaveRequest):
    """保存记忆

    ``conflict_check=true`` 时走 P3 冲突消解（NOOP 复用既有 ID / UPDATE 写新行
    并使旧行失效 / ADD 正常写入）, 响应额外带 ``op`` 字段。
    """
    if data.memory_type not in ("working", "episodic", "semantic", "auto"):
        raise HTTPException(status_code=422, detail="不支持的记忆类型")
    try:
        mm = get_memory_manager()
        if data.conflict_check:
            memory_id, op = mm.memorize_with_conflict_check(
                content=data.content,
                memory_type=data.memory_type,
                importance=data.importance,
                tags=data.tags,
                session_id=data.session_id,
                scope=data.scope,
            )
            return {"id": memory_id, "op": op, "status": "ok"}
        memory_id = mm.memorize(
            content=data.content,
            memory_type=data.memory_type,
            importance=data.importance,
            tags=data.tags,
            session_id=data.session_id,
            scope=data.scope,
        )
        if not memory_id:
            raise HTTPException(status_code=422, detail="记忆未写入")
        return {"id": memory_id, "status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/delete")
@with_db_lock
def delete_memory(data: MemoryDeleteRequest):
    """删除记忆"""
    try:
        mm = get_memory_manager()
        # 尝试从所有类型中删除(working 通过合成 id 支持单条删除)
        for mtype in ["episodic", "semantic", "working"]:
            if mm.delete_memory(data.id, mtype):
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="记忆不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

