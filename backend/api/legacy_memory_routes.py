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
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.data.database import get_database
from backend.memory import get_memory_manager

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
    # Gap E (Task 5): 渲染器桥 (T1) 发 { memory_id }，preload 直传；
    # 兼容 legacy { id } 两种拼法，端到端打通 Memory 页删除。
    id: Optional[str] = None
    memory_id: Optional[str] = None

    def resolve_id(self) -> Optional[str]:
        """优先 memory_id（渲染器桥），兼容 legacy { id }。"""
        if self.memory_id and self.id and self.memory_id != self.id:
            raise HTTPException(status_code=422, detail="memory id mismatch")
        return self.memory_id or self.id


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


# ---- P0-2 已学偏好与画像刷新 -------------------------------------------


@router.get("/memory/preferences/learned")
def list_learned_preferences():
    """列出进化任务学到的偏好（preferences 表 pref_* 键）。

    这些是 ``PreferenceLearningTask`` 通过关键词 / LLM 双路分析得出的稳定
    偏好；每次进化执行会同步写入 user_profile（category=preference），
    从而进入 system prompt 冻结快照。
    """
    try:
        db = get_database()
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT key, value, value_type, category, updated_at "
            "FROM preferences WHERE key LIKE 'pref_%' "
            "ORDER BY updated_at DESC"
        )
        rows = cursor.fetchall()
        return {
            "items": [
                {
                    "key": row["key"],
                    "value": row["value"],
                    "value_type": row["value_type"],
                    "category": row["category"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LearnedPreferenceUpdate(BaseModel):
    """手动纠正已学偏好的请求体。"""

    class Config:
        extra = "forbid"

    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


@router.put("/memory/preferences/learned")
@with_db_lock
def update_learned_preference(data: LearnedPreferenceUpdate):
    """手动纠正某条已学偏好。body: ``{key, value}``, key 必须以 ``pref_`` 开头。

    同时更新 ``preferences`` 表与 ``user_profile``（category=preference）——
    让手动纠正立即进冻结快照候选集；用户若需立即生效可再调
    POST /memory/profile/refresh。

    为避免反复纠正同一偏好时 ``user_profile`` 累积冲突条目
    （同一 key 多条不同 value 同时出现在快照里），写之前先用
    ``list()`` + ``delete(id)`` 清理同 key 旧条目。
    """
    key = data.key.strip()
    value = data.value.strip()
    if not key.startswith("pref_"):
        raise HTTPException(status_code=422, detail="key 必须以 'pref_' 开头")
    if not value:
        raise HTTPException(status_code=422, detail="value 不能为空")
    try:
        import time as _t

        from backend.memory.user_profile import get_user_profile

        db = get_database()
        now_ts = int(_t.time())
        conn = db.get_connection()
        conn.execute(
            "INSERT INTO preferences (key, value, value_type, category, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, "string", "preference", now_ts, now_ts),
        )
        conn.commit()
        short_key = key[len("pref_") :]
        prefix = f"用户偏好 {short_key}:"
        profile = get_user_profile()
        # 清理同 key 旧条目 —— 避免 user_profile 里堆积相互冲突的偏好
        for item in profile.list():
            content = item.get("content") or ""
            if content.startswith(prefix):
                profile.delete(item["id"])
        profile.add(
            content=f"用户偏好 {short_key}: {value}",
            category="preference",
            importance=6,
        )
        return {"status": "ok", "key": key, "value": value}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/profile/refresh")
@with_db_lock
def refresh_user_profile():
    """显式刷新 user_profile 冻结快照。

    进化任务（``PreferenceLearningTask``）写 user_profile 时故意不调
    ``invalidate()`` —— 保 prefix cache（hermes 语义）。用户若希望学到的
    偏好立即进 system prompt（不等下次会话），调本端点手动刷新。
    """
    try:
        from backend.memory.user_profile import get_user_profile

        store = get_user_profile()
        store.invalidate()
        store.load()
        return {
            "status": "ok",
            "items_count": len(store.list()),
            "snapshot_chars": len(store.get_snapshot()),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- P0-3 召回指标与反馈 ---------------------------------------------------


class RecallFeedbackRequest(BaseModel):
    """召回反馈上报体。"""

    class Config:
        extra = "forbid"

    log_id: str = Field(min_length=1)
    feedback: str = Field(regex="^(up|down)$")


@router.get("/memory/recall/metrics")
def get_recall_metrics(limit: int = 20):
    """召回指标：总体 + **按 A/B 变体分组**的对比。

    ``by_variant`` 是本轮改造的核心产出 —— 让 ``adapter.py`` 里那个早已
    存在、却从未被分别度量过的 A/B 权重实验（A=[0.2,0.8] / B=[0.5,0.5]）
    第一次可比较。
    """
    try:
        from backend.memory.recall_log_store import aggregate_metrics, list_recent

        db = get_database()
        metrics = aggregate_metrics(db)
        recent = list_recent(db, limit=max(1, min(limit, 100)))
        return {
            "metrics": metrics,
            "recent": recent,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/recall/feedback")
@with_db_lock
def submit_recall_feedback(data: RecallFeedbackRequest):
    """上报一次召回的用户反馈（up / down）。

    回填 ``memory_recall_log.user_feedback`` —— 落库后正反馈计数不再恒为 0，
    A/B 变体的满意度才可比。
    """
    try:
        from backend.memory.recall_log_store import set_feedback

        db = get_database()
        if not set_feedback(db, data.log_id, data.feedback):
            raise HTTPException(status_code=404, detail="召回记录不存在")
        return {"status": "ok", "log_id": data.log_id, "feedback": data.feedback}
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
        target_id = data.resolve_id()
        if not target_id:
            raise HTTPException(status_code=422, detail="memory id required")
        for mtype in ["episodic", "semantic", "working"]:
            if mm.delete_memory(target_id, mtype):
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="记忆不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
