# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Task 4.5 —— 记忆级用户反馈（👍/👎）持久化。

单表 ``memories_feedback``，一条记忆只保留最新一条反馈（id 由
``memory_type:memory_id`` 派生，写入走 INSERT OR REPLACE）。这样既避免了
额外唯一索引，也不依赖 SQLite 3.24+ 的 ``ON CONFLICT`` 语法 —— win7 安装包
捆绑的旧版 SQLite 同样可用。

所有函数接收由调用方持有的 ``sqlite3.Connection``；调用方负责在
``_SQLITE_LOCK`` 内使用（见 ``make_with_db_lock``）。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

VALID_FEEDBACK = ("up", "down", "neutral")
VALID_MEMORY_TYPES = ("episodic", "semantic")

_MAX_REASON_LEN = 500


def _feedback_row_id(memory_id: str, memory_type: str) -> str:
    return f"{memory_type}:{memory_id}"


def _normalize_reason(reason: Optional[str]) -> Optional[str]:
    if reason is None:
        return None
    text = str(reason).strip()
    if not text:
        return None
    return text[:_MAX_REASON_LEN]


def upsert_feedback(
    db: Any,
    memory_id: str,
    memory_type: str,
    feedback: str,
    reason: Optional[str] = None,
) -> None:
    """写入/覆盖一条记忆反馈。

    Raises:
        ValueError: feedback 或 memory_type 不在白名单内。
    """
    if feedback not in VALID_FEEDBACK:
        raise ValueError(f"invalid feedback: {feedback!r}")
    if memory_type not in VALID_MEMORY_TYPES:
        raise ValueError(f"invalid memory_type: {memory_type!r}")

    conn = db.get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO memories_feedback"
        "(id, memory_id, memory_type, feedback, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            _feedback_row_id(memory_id, memory_type),
            memory_id,
            memory_type,
            feedback,
            _normalize_reason(reason),
            int(time.time() * 1000),
        ),
    )
    conn.commit()


def get_feedback(
    db: Any, memory_id: str, memory_type: str
) -> Optional[Dict[str, Any]]:
    """读取一条记忆的最新反馈；无记录返回 None。"""
    try:
        conn = db.get_connection()
        row = conn.execute(
            "SELECT feedback, reason, created_at FROM memories_feedback "
            "WHERE id = ?",
            (_feedback_row_id(memory_id, memory_type),),
        ).fetchone()
    except Exception:  # noqa: BLE001 — 旧库缺表时按"无反馈"处理
        logger.debug("memories_feedback lookup skipped", exc_info=True)
        return None
    if row is None:
        return None
    return {
        "feedback": row["feedback"],
        "reason": row["reason"],
        "created_at": row["created_at"],
    }


def attach_feedback(db: Any, items: Iterable[Dict[str, Any]]) -> None:
    """给 list 结果的 episodic / semantic 行补 ``user_feedback`` 字段。

    原地修改；查不到反馈或旧库缺表时统一填 None（前端按"未反馈"渲染）。
    一次 IN 查询批量取回，避免每条卡片各打一次数据库（N+1）。
    """
    rows: List[Dict[str, Any]] = list(items)
    for item in rows:
        item.setdefault("user_feedback", None)

    keys: List[Tuple[str, str]] = []
    for item in rows:
        memory_type = item.get("source") or item.get("layer")
        memory_id = item.get("id")
        if memory_type in VALID_MEMORY_TYPES and memory_id:
            keys.append((str(memory_id), str(memory_type)))
    if not keys:
        return

    row_ids = [_feedback_row_id(memory_id, memory_type) for memory_id, memory_type in keys]
    placeholders = ",".join("?" for _ in row_ids)
    try:
        conn = db.get_connection()
        cursor = conn.execute(
            "SELECT memory_id, memory_type, feedback FROM memories_feedback "
            f"WHERE id IN ({placeholders})",
            row_ids,
        )
        feedback_by_id = {
            _feedback_row_id(row["memory_id"], row["memory_type"]): row["feedback"]
            for row in cursor.fetchall()
        }
    except Exception:  # noqa: BLE001 — 旧库缺表: 降级为全部未反馈
        logger.debug("memories_feedback batch lookup skipped", exc_info=True)
        return

    for item in rows:
        memory_type = item.get("source") or item.get("layer")
        memory_id = item.get("id")
        if memory_type in VALID_MEMORY_TYPES and memory_id:
            item["user_feedback"] = feedback_by_id.get(
                _feedback_row_id(str(memory_id), str(memory_type))
            )
