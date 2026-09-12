"""
Legacy 会话 CRUD 路由 (S7-3, P7 — 从 legacy_routes.py 拆出)。

拆分原则 (零行为变更):
- 复用 legacy_routes 的同一个 ``router`` 对象 —— 本模块被 import 时端点
  即注册到该 router; main.py 必须在 ``include_router(legacy_router)``
  之前 import 本模块 (import 顺序即装配顺序)。
- 会话 CRUD + 会话级模型覆盖 (G5) 属纯 DB/KV 操作, 不依赖 chat
  producer/stream 机制, 可独立成模块; compact/fork 仍留在
  legacy_routes (与 LLM 装配、流注册表耦合)。
- 委托范围: 7 个端点 (POST/GET /sessions, GET/PUT /sessions/{id}/model,
  GET/PATCH/DELETE /sessions/{id})。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel

from backend.api.error_contract import error_json
from backend.api.legacy_routes import (
    SessionCreate,
    SessionUpdate,
    _run_db_sync,
    get_session_repo,
    router,
)
from backend.chat.compaction import (
    MIN_COMPACT_MESSAGE_COUNT,
    CompactionError,
    compact_messages,
    should_compact,
)
from backend.data.database import get_database, make_with_db_lock
from backend.data.session_repo import (
    ForkSourceNotFoundError,
    MessageRepository,
    SessionRepository,
    fork_session as fork_session_core,
)
from backend.orchestration.llm_factory import (
    SESSION_MODEL_OVERRIDES_KEY,
    load_session_model_overrides,
)

# S7-3/L1 (P8): 本模块自持 with_db_lock 绑定 —— make_with_db_lock 会把
# wrapper.__globals__ 重绑到调用方模块, FastAPI 在该命名空间解析 body 模型
# (ForkSessionRequest 定义于本模块, 不在 legacy_routes)。
with_db_lock = make_with_db_lock(globals())

logger = logging.getLogger(__name__)

__all__ = ["SessionModelOverride"]


class SessionModelOverride(BaseModel):
    model_config = {"protected_namespaces": ()}

    model: str


@router.post("/sessions", response_model=dict)
@with_db_lock
def create_session(data: SessionCreate, repo: SessionRepository = Depends(get_session_repo)):
    """创建新会话"""
    session = repo.create(title=data.title, parent_id=data.parent_id)
    return session.to_dict()


@router.get("/sessions", response_model=List[dict])
@with_db_lock
def list_sessions(
    limit: int = 100, offset: int = 0, repo: SessionRepository = Depends(get_session_repo)
):
    """获取会话列表"""
    sessions = repo.list(limit=limit, offset=offset)
    result = [s.to_dict() for s in sessions]
    # P0-4 (UI 优化方案 2026-09-13): 批量附加 last_message_preview(每个会话最后一条
    # user/assistant 消息截断 80 字符),空会话 → None。
    previews = _batch_last_message_previews([s.id for s in sessions])
    for item in result:
        item["last_message_preview"] = previews.get(item["id"])
    return result


def _batch_last_message_previews(session_ids: List[str]) -> Dict[str, str]:
    """批量取每个会话的最后一条 user/assistant 消息预览(截断 80 字符)。"""
    if not session_ids:
        return {}
    conn = get_database().get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in session_ids)
    cursor.execute(
        f"""
        SELECT m.session_id, SUBSTR(m.content, 1, 80) AS preview
        FROM messages m
        INNER JOIN (
            SELECT session_id, MAX(created_at) AS max_created
            FROM messages
            WHERE role IN ('user', 'assistant')
              AND session_id IN ({placeholders})
            GROUP BY session_id
        ) latest ON m.session_id = latest.session_id
                AND m.created_at = latest.max_created
        WHERE m.role IN ('user', 'assistant')
          AND m.session_id IN ({placeholders})
        """,
        list(session_ids) + list(session_ids),
    )
    return {row["session_id"]: row["preview"] for row in cursor.fetchall()}


@router.get("/sessions/{session_id}/model")
def get_session_model(session_id: str):
    """读取某会话的模型覆盖；未设置返回 {"model": null}。"""
    override = load_session_model_overrides().get(session_id)
    return {"session_id": session_id, "model": override}


@router.put("/sessions/{session_id}/model")
def set_session_model(session_id: str, payload: SessionModelOverride):
    """设置/清除（model 传空串）某会话的模型覆盖。

    设置后该会话的 chat 固定用此模型（端点仍取全局选择）；传空串清除
    覆盖，回到全局选择。非法值整体拒绝，绝不部分写入。
    """
    model = payload.model.strip() if isinstance(payload.model, str) else ""
    overrides = load_session_model_overrides()
    if model:
        overrides[session_id] = model
    else:
        overrides.pop(session_id, None)
    try:
        from backend.data.settings_repo import SettingsRepository

        SettingsRepository().set(
            SESSION_MODEL_OVERRIDES_KEY,
            json.dumps(overrides, ensure_ascii=False),
            value_type="json",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"写入会话模型覆盖失败: {exc}")
    return {"session_id": session_id, "model": model or None}


@router.get("/sessions/{session_id}", response_model=dict)
@with_db_lock
def get_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """获取单个会话"""
    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.patch("/sessions/{session_id}", response_model=dict)
@with_db_lock
def update_session(
    session_id: str, data: SessionUpdate, repo: SessionRepository = Depends(get_session_repo)
):
    """更新会话"""
    update_data = {}
    if data.title is not None:
        update_data["title"] = data.title
    if data.is_pinned is not None:
        update_data["is_pinned"] = 1 if data.is_pinned else 0

    if update_data:
        repo.update(session_id, **update_data)

    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.delete("/sessions/{session_id}")
@with_db_lock
def delete_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """删除会话"""
    if not repo.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}



# ==================== 会话内容操作 (L1/L2, P8 — 从 legacy_routes 拆入) ====================
#
# 手动压缩 / 分叉 / 消息删除 / 消息列表 / 跨会话搜索。
# 共享机械 (_build_compaction_llm_callable / _persist_compaction /
# _compact_in_progress / _safe_log_field) 仍属 legacy_routes —— producer 的
# 自动压缩钩子同样使用; 经模块属性访问以保持测试 monkeypatch 目标兼容。

import backend.api.legacy_routes as _legacy_routes


@router.post("/sessions/{session_id}/compact", response_model=dict)
async def compact_session(session_id: str):
    """手动压缩会话上下文（M4，对应前端 /compact slash action）。

    - 200 + ``{"ok": true, "compacted": true, "before", "after", "removed"}``
    - 200 + ``{"ok": true, "compacted": false, "reason", ...}`` — 低于压缩
      地板（消息数 < 12 或 token 未达阈值），DB 不动
    - 404 — 会话不存在
    - 409 + ``{"ok": false, "error": "compact_in_progress"}`` — 同会话压缩
      正在进行（重复触发）
    - 502 + ``{"ok": false, "error"}`` — 无 LLM 配置 / 摘要失败 / 落盘失败，
      DB 不动（落盘走单事务，失败整体回滚）
    """
    session_repo = SessionRepository()
    if await _run_db_sync(session_repo.get, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    message_repo = MessageRepository()
    messages = await _run_db_sync(
        message_repo.get_by_session, session_id, limit=100000
    )
    before = len(messages)

    if not should_compact(messages):
        reason = (
            "below_message_floor"
            if before < MIN_COMPACT_MESSAGE_COUNT
            else "below_token_threshold"
        )
        return {
            "ok": True,
            "compacted": False,
            "reason": reason,
            "before": before,
            "after": before,
            "removed": 0,
        }

    if session_id in _legacy_routes._compact_in_progress:
        return error_json(
            409, "compact_in_progress", "该会话正在压缩中，请勿重复触发"
        )

    llm_complete = _legacy_routes._build_compaction_llm_callable()
    if llm_complete is None:
        return error_json(
            502, "llm_not_configured", "没有可用的 LLM 配置，无法生成压缩摘要"
        )

    _legacy_routes._compact_in_progress.add(session_id)
    try:
        try:
            new_messages, removed_count = await compact_messages(messages, llm_complete)
        except CompactionError as exc:
            logger.warning(
                "[M4] compact session=%s 失败(DB 未改动): %s", _legacy_routes._safe_log_field(session_id), exc
            )
            return error_json(502, "compaction_failed", str(exc))

        try:
            after = await _run_db_sync(
                _legacy_routes._persist_compaction,
                session_id,
                messages,
                new_messages,
                removed_count,
            )
        except Exception as exc:
            # 单事务已回滚——DB 保持压缩前状态（CRITICAL-1 的核心保证）。
            logger.warning(
                "[M4] compact session=%s 落盘失败(事务已回滚, DB 未改动): %s",
                _legacy_routes._safe_log_field(session_id),
                exc,
            )
            return error_json(
                502, "persist_failed", "压缩结果落盘失败，数据库未改动"
            )
    finally:
        _legacy_routes._compact_in_progress.discard(session_id)

    logger.info(
        "[M4] compact session=%s 完成: before=%s after=%s removed=%s",
        _legacy_routes._safe_log_field(session_id),
        before,
        after,
        removed_count,
    )
    return {"ok": True, "compacted": True, "before": before, "after": after, "removed": removed_count}


class ForkSessionRequest(BaseModel):
    """POST /sessions/{session_id}/fork 请求体。"""

    at_message_id: Optional[str] = None
    title: Optional[str] = None
    # U5' (对标增强第五轮批次 A): 开区间截断——复制 at_message_id 之前的
    # 消息（不含本身）。编辑重发据此分叉出"被编辑消息之前"的前缀。
    before_message: bool = False


@router.post("/sessions/{session_id}/fork", response_model=dict)
@with_db_lock
def fork_session(session_id: str, data: ForkSessionRequest):
    """从当前会话分叉出新会话（M4）。

    复制 ``at_message_id`` 及之前的全部消息（省略时复制全部）到新会话，
    消息获得新 id 但保留顺序 / 角色 / 内容 / 时间戳。新会话写入
    ``fork_root=<源 id>`` 与 ``forked_at_message_id``。

    刻意采用**全量前缀复制**而非计划文档最初的 copy-on-write 设计：
    桌面级会话只有数百条消息，复制更简单安全（详见 docs/plans/2026-07-29_session-compact-fork-m4.md）。

    - 200 + 新会话 JSON（含 fork_root / forked_at_message_id）
    - 404 + 结构化 detail — 源会话或分叉点消息不存在
    """
    try:
        forked = fork_session_core(
            SessionRepository(),
            MessageRepository(),
            session_id,
            at_message_id=data.at_message_id,
            title=data.title,
            before_message=data.before_message,
        )
    except ForkSourceNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"type": f"{exc.kind}_not_found", "message": str(exc)},
        ) from exc
    return forked.to_dict()


@router.post("/messages/{message_id}/delete")
@with_db_lock
def delete_message(message_id: str):
    """删除单条消息（物理删除，非软删）。

    对应 Tauri command ``delete_message`` (PR-2):
    - 现有消息 → 200 + ``{"deleted": true}``
    - 不存在消息 → 404 + 结构化 detail (前端可分类处理)
    - 重复删除 → 第二次 404 (幂等性)

    注: 选 POST 而非 DELETE 是为了与项目其他 `/<resource>/<id>/delete` 路由
    (sessions/{id}/delete) 保持一致; 真正的 RESTful DELETE 在 v2 改造时再做。
    """
    from backend.data.session_repo import MessageRepository

    deleted = MessageRepository().delete(message_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "message_not_found",
                "message": f"message {message_id} not found",
            },
        )
    return {"deleted": True}


@router.get("/sessions/{session_id}/messages", response_model=List[dict])
@with_db_lock
def get_messages(session_id: str, limit: int = 100, offset: int = 0):
    """获取会话消息"""
    repo = MessageRepository()
    messages = repo.get_by_session(session_id, limit=limit, offset=offset)
    return [m.to_dict() for m in messages]


def _snippet_around(content: str, needle: str, window: int = 80) -> str:
    """取命中点前后 ``window`` 字符的摘录（前后越界截断，中间不省略号——
    前端按单行截断展示）。多命中取第一处。"""
    lowered = content.lower()
    idx = lowered.find(needle.lower())
    if idx < 0:
        return content[: window * 2]
    start = max(0, idx - window)
    end = min(len(content), idx + len(needle) + window)
    return content[start:end]


@router.get("/search/messages")
@with_db_lock
def search_messages(
    q: str = Query(min_length=2, max_length=200),
    session_id: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=50),
):
    """跨会话消息全文搜索（F12，round5 批次 B）。

    LIKE 子串匹配（通配符转义，转义符用 ``!`` ——反斜杠在部分驱动/书写
    环境下不是稳定的单字符 ESCAPE），仅 user/assistant 行（tool/system 无
    检索价值）；新→旧排序；取 limit+1 条探测 has_more，避免 COUNT 双查。
    """
    needle = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    pattern = f"%{needle}%"
    conn = get_database().get_connection()
    sql = """
        SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.role IN ('user', 'assistant') AND m.content LIKE ? ESCAPE '!'
    """
    params: List[Any] = [pattern]
    if session_id:
        sql += " AND m.session_id = ?"
        params.append(session_id)
    sql += " ORDER BY m.created_at DESC LIMIT ?"
    params.append(limit + 1)
    rows = conn.execute(sql, params).fetchall()

    has_more = len(rows) > limit
    results = [
        {
            "message_id": row["id"],
            "session_id": row["session_id"],
            "session_title": row["title"],
            "role": row["role"],
            "snippet": _snippet_around(row["content"] or "", q),
            "created_at": row["created_at"],
        }
        for row in rows[:limit]
    ]
    return {"results": results, "has_more": has_more}


