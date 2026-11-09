"""Task 4.3 —— 批量清理低质量记忆的 API 端点。

两个端点:
- GET  /memory/quality-candidates: 返回按质量分升序排列的候选列表,
  供前端"低质量候选"过滤按钮渲染。
- POST /memory/batch-delete: 批量删除用户选中的记忆,逐条走
  MemoryManager.delete_memory (episodic 软删除 / semantic 硬删除),
  并写 memories_evolution_log 审计。

scorer 基于 episodic + semantic 当前有效行构建,与 /memory/list 的
'all' 视图共享同一语料范围,保证同一批数据上的分数一致。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由 with_db_lock 闭包解析
    _SQLITE_LOCK,
    make_with_db_lock,
)
from backend.memory import get_memory_manager
from backend.memory.quality_scorer import MemoryQualityScorer
from backend.scheduler.evolution import _write_evolution_log

logger = logging.getLogger(__name__)


def with_db_lock(func):
    """串行化 SQLite 访问 (镜像 legacy_memory_list_routes)。"""
    return make_with_db_lock(globals())(func)


router = APIRouter()

_QUALITY_CANDIDATES_MAX_LIMIT = 200
_QUALITY_CANDIDATES_DEFAULT_LIMIT = 50
_QUALITY_CANDIDATES_DEFAULT_THRESHOLD = 0.3
_BATCH_DELETE_MAX_ITEMS = 50


# ==================== 质量候选列表 ====================


@router.get("/memory/quality-candidates")
@with_db_lock
def get_quality_candidates(
    limit: int = _QUALITY_CANDIDATES_DEFAULT_LIMIT,
    threshold: float = _QUALITY_CANDIDATES_DEFAULT_THRESHOLD,
):
    """返回质量分低于阈值的 episodic + semantic 记忆,按分数升序 (最差优先)。

    Args:
        limit: 返回条数上限,默认 50, 最高 200
        threshold: 质量分阈值,默认 0.3, 低于此值的记录进入候选

    Returns:
        { items: [{id, content, memory_type, importance, quality_score,
                   created_at_ms, access_count}] }
    """
    try:
        safe_limit = max(1, min(_QUALITY_CANDIDATES_MAX_LIMIT, int(limit)))
        safe_threshold = max(0.0, min(1.0, float(threshold)))

        mm = get_memory_manager()
        # 取当前有效行 (store 内部已过滤 is_valid=1 / invalid_at IS NULL)
        # 取大一些用于评分,再筛 + 截断
        fetch_limit = max(safe_limit, _QUALITY_CANDIDATES_MAX_LIMIT)
        episodic_items = mm.episodic.get_recent(limit=fetch_limit)
        semantic_items = mm.semantic.get_recent(limit=fetch_limit)

        # scorer 与 /memory/list 'all' 视图同源:episodic + semantic 一起构建
        scorer = MemoryQualityScorer(corpus=list(episodic_items) + list(semantic_items))

        candidates: List[Dict[str, Any]] = []
        for record, memory_type in (
            [(r, "episodic") for r in episodic_items]
            + [(r, "semantic") for r in semantic_items]
        ):
            try:
                score = round(scorer.calculate_quality_score(record), 3)
            except Exception:
                # 评分失败 → 跳过,不让一条异常数据阻塞整页候选
                logger.debug(
                    "quality score failed for %s:%s",
                    memory_type,
                    record.get("id"),
                    exc_info=True,
                )
                continue
            if score >= safe_threshold:
                continue
            candidates.append(
                {
                    "id": record.get("id"),
                    "content": record.get("content", ""),
                    "memory_type": memory_type,
                    "importance": record.get("importance", 0),
                    "quality_score": score,
                    "created_at_ms": record.get("created_at"),
                    "access_count": record.get("access_count", 0),
                }
            )

        # 按分数升序 (最差优先);同分按 created_at 升序 (旧的优先)
        candidates.sort(
            key=lambda c: (
                c["quality_score"],
                c.get("created_at_ms") or 0,
            )
        )
        return {"items": candidates[:safe_limit]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 批量删除 ====================


@router.post("/memory/batch-delete")
@with_db_lock
def batch_delete_memories(items: List[Dict[str, Any]]):
    """批量删除用户选中的记忆。

    Args:
        items: 待删除列表 [{id, memory_type}]。上限 50 条。
            memory_type 必须是 'episodic' | 'semantic' | 'working';
            其他类型直接记入 failed,不调用后端 store。

    Returns:
        { deleted: int, failed: [{id, reason}] }

    删除语义:
        episodic → 软删除 (is_valid=0) + 向量清理
        semantic → 硬删除 + FTS + 向量清理
        working  → deque 移除
    全部走 MemoryManager.delete_memory, 与单条删除保持一致语义。
    """
    if not items:
        return {"deleted": 0, "failed": []}
    if len(items) > _BATCH_DELETE_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"单次批量删除上限 {_BATCH_DELETE_MAX_ITEMS} 条,收到 {len(items)} 条",
        )

    mm = get_memory_manager()
    db = mm.episodic.db  # episodic / semantic 共享同一 Database 实例

    deleted = 0
    failed: List[Dict[str, str]] = []

    for entry in items:
        memory_id = entry.get("id") if isinstance(entry, dict) else None
        memory_type = entry.get("memory_type") if isinstance(entry, dict) else None
        if not memory_id or memory_type not in ("episodic", "semantic", "working"):
            failed.append(
                {
                    "id": memory_id or "",
                    "reason": f"invalid memory_type: {memory_type!r}",
                }
            )
            continue

        try:
            ok = mm.delete_memory(memory_id, memory_type)
        except Exception as e:
            logger.warning(
                "batch-delete failed for %s:%s: %s",
                memory_type,
                memory_id,
                e,
            )
            failed.append({"id": memory_id, "reason": str(e)})
            continue

        if not ok:
            failed.append({"id": memory_id, "reason": "store returned False (not found)"})
            continue

        # 审计日志: best-effort, 写失败不阻断删除
        try:
            _write_evolution_log(
                db=db,
                memory_type=memory_type,
                memory_id=memory_id,
                operation="batch_delete",
                before_content=f"{memory_type}:{memory_id}",
                after_content="(deleted)",
                reason="user:batch_delete",
            )
        except Exception:
            logger.debug("evolution log failed for %s", memory_id, exc_info=True)

        deleted += 1

    return {"deleted": deleted, "failed": failed}
