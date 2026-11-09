"""Task 4.5 —— 记忆级用户反馈端点。

``POST /memory/{memory_id}/feedback``：用户对单条记忆标记 👍 / 👎 / 中性，
为后续调整质量评分器积累信号。与 ``/memory/recall/feedback`` 的区别：
后者按**一次召回**的 ``log_id`` 回填 ``memory_recall_log``（A/B 实验指标），
本端点按**一条记忆**落 ``memories_feedback``（记忆本身是否准确/有用）。

存在性校验直接查表，不走 ``episodic.get_by_id`` —— 后者有
``_update_access`` 副作用，会污染质量分的 recency/usage 维度。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由 with_db_lock 闭包解析
    _SQLITE_LOCK,
    make_with_db_lock,
)
from backend.memory import get_memory_manager
from backend.memory.feedback_store import (
    VALID_FEEDBACK,
    VALID_MEMORY_TYPES,
    upsert_feedback,
)

logger = logging.getLogger(__name__)


def with_db_lock(func):
    """串行化 SQLite 访问 (镜像 legacy_memory_quality_routes)。"""
    return make_with_db_lock(globals())(func)


router = APIRouter()

_MEMORY_TABLE_BY_TYPE = {
    "episodic": "memories_episodic",
    "semantic": "memories_semantic",
}


class MemoryFeedbackRequest(BaseModel):
    """记忆级反馈上报体。"""

    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(pattern="^(up|down|neutral)$")
    memory_type: str = Field(default="episodic", pattern="^(episodic|semantic)$")
    reason: Optional[str] = Field(default=None, max_length=500)


def _memory_exists(db, memory_id: str, memory_type: str) -> bool:
    """只读存在性检查，不触发 access_count / accessed_at 更新。"""
    table = _MEMORY_TABLE_BY_TYPE[memory_type]
    # 表名来自白名单常量，可安全拼接；memory_id 走参数绑定。
    if memory_type == "episodic":
        sql = f"SELECT 1 FROM {table} WHERE id = ? AND is_valid = 1 LIMIT 1"
    else:
        sql = f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1"
    conn = db.get_connection()
    return conn.execute(sql, (memory_id,)).fetchone() is not None


@router.post("/memory/{memory_id}/feedback")
@with_db_lock
def submit_memory_feedback(memory_id: str, data: MemoryFeedbackRequest):
    """写入一条记忆的最新用户反馈（重复提交即覆盖）。

    Returns:
        {status: "ok", memory_id, memory_type, feedback}

    Raises:
        404: 记忆不存在（episodic 已软删除的视为不存在）
        400: feedback / memory_type 不在白名单（pydantic pattern 已挡一层，
             这里保留防御性校验供非 HTTP 调用方复用）
    """
    if data.feedback not in VALID_FEEDBACK or data.memory_type not in VALID_MEMORY_TYPES:
        raise HTTPException(status_code=400, detail="非法的反馈参数")

    try:
        mm = get_memory_manager()
        db = mm.episodic.db  # episodic / semantic 共享同一 Database 实例

        if not _memory_exists(db, memory_id, data.memory_type):
            raise HTTPException(status_code=404, detail="记忆不存在")

        upsert_feedback(
            db=db,
            memory_id=memory_id,
            memory_type=data.memory_type,
            feedback=data.feedback,
            reason=data.reason,
        )
        return {
            "status": "ok",
            "memory_id": memory_id,
            "memory_type": data.memory_type,
            "feedback": data.feedback,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("submit_memory_feedback failed for %s", memory_id)
        raise HTTPException(status_code=500, detail=str(e))
