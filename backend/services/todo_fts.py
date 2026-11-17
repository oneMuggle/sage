"""待办全文搜索（FTS5）同步与查询助手。

与 ``memories_semantic_fts`` 同一模式：独立（存内容）FTS5 表 + jieba 分词 +
Python 侧显式同步（无触发器）。本模块只负责 ``todos_fts`` 的读写；
过滤条件叠加与降级逻辑在 :class:`~backend.services.todo_service.TodoService`。

FTS 为非关键路径：所有失败只记 warning，由调用方降级 LIKE 或静默跳过。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, List, Optional

from backend.data.database import TODOS_FTS_TABLE, _segment_for_index

logger = logging.getLogger(__name__)


def upsert_todo_fts(
    db: Any, todo_id: int, title: str, description: Optional[str]
) -> None:
    """把单行同步进 todos_fts（先删后插，避免 rowid 冲突）。"""
    try:
        conn = db.get_connection()
        conn.execute(f"DELETE FROM {TODOS_FTS_TABLE} WHERE rowid = ?", (todo_id,))
        conn.execute(
            f"INSERT INTO {TODOS_FTS_TABLE}(rowid, title, description) "
            "VALUES (?, ?, ?)",
            (todo_id, _segment_for_index(title), _segment_for_index(description)),
        )
        conn.commit()
    except sqlite3.DatabaseError as exc:
        logger.warning("todo FTS 同步失败（rowid=%s）: %s", todo_id, exc)


def delete_todo_fts(db: Any, todo_id: int) -> None:
    """从索引中删除一行（行本身已从主表删除时）。"""
    try:
        conn = db.get_connection()
        conn.execute(f"DELETE FROM {TODOS_FTS_TABLE} WHERE rowid = ?", (todo_id,))
        conn.commit()
    except sqlite3.DatabaseError as exc:
        logger.warning("todo FTS 删除失败（rowid=%s）: %s", todo_id, exc)


def match_ids(db: Any, q: str) -> Optional[List[int]]:
    """FTS MATCH 命中的 id 列表。

    FTS 表缺失/损坏/分词异常时返回 ``None``，由调用方降级为 LIKE。
    """
    try:
        from backend.memory.chinese_tokenizer import tokenize_for_search

        match = tokenize_for_search(q)
        if match.strip() in ("", '""'):
            return None
        conn = db.get_connection()
        rows = conn.execute(
            f"SELECT rowid FROM {TODOS_FTS_TABLE} "
            f"WHERE {TODOS_FTS_TABLE} MATCH ?",
            (match,),
        ).fetchall()
        return [int(row[0]) for row in rows]
    except Exception as exc:  # noqa: BLE001 — 搜索降级边界
        logger.warning("todo FTS 查询失败，降级 LIKE: %s", exc)
        return None


def apply_search_filter(
    db: Any, query: str, params: List[Any], q: Optional[str]
) -> tuple:
    """把全文搜索条件叠加到 list/count 共用的 WHERE 片段上。

    FTS MATCH 命中 → ``AND id IN (...)``；FTS 不可用/查询失败 →
    标题/描述 LIKE 降级；空结果 → ``AND 0=1``。
    """
    if not q or not q.strip():
        return query, params

    matched = match_ids(db, q)
    if matched is None:
        like = f"%{q.strip()}%"
        query += " AND (title LIKE ? OR description LIKE ?)"
        params.extend([like, like])
    elif not matched:
        query += " AND 0=1"
    else:
        placeholders = ",".join("?" for _ in matched)
        query += f" AND id IN ({placeholders})"
        params.extend(matched)
    return query, params
