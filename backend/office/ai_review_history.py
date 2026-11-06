# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Office AI 审校历史（M3 阶段）.

每次 ``POST /office/ai/review`` 完成后调用 :func:`record` 追加一行审计记录，
``GET /office/doc/{id}/ai-reviews`` 通过 :func:`list_for_document` 回放历史，
记录本次使用的规范书、模型、耗时与 token 用量，便于追溯和成本可见。

设计规则（与 ``selfcheck_history`` 对齐）:

* :func:`record` 是 **best-effort** 的 —— 整个函数体包在自己的 try/except 里，
  绝不向上抛异常。表缺失（旧库未迁移）、连接已关闭、summary 不可序列化等
  情况全部降级为 debug 日志，绝不打断产生它的审校请求。
* :func:`list_for_document` 是读侧（``GET /office/doc/{id}/ai-reviews``）:
  最新在前，``summary`` 反序列化为 dict。
* Schema 定义在 ``backend.data.database.init_db``（additive、幂等）:

    office_ai_reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        doc_id TEXT NOT NULL,
        spec_id TEXT,
        model TEXT,
        scope TEXT NOT NULL,
        issue_count INTEGER NOT NULL DEFAULT 0,
        summary TEXT,
        duration_ms INTEGER,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        created_at INTEGER NOT NULL
    )  + index (doc_id, created_at)

* 分层: 本模块属于与连接无关的 office 层，``backend.data.database`` 只在
  :func:`record` 内部懒导入（仅当调用方未传连接时）—— office → data
  不得出现在模块加载期。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["list_for_document", "record"]

#: scope 域（记录用；不做硬校验——审计写入永远不能因新增 scope 而失败）。
VALID_SCOPES = frozenset({"full", "selection", "section"})


def record(
    doc_id: str,
    *,
    scope: str,
    issue_count: int,
    spec_id: Optional[str] = None,
    model: Optional[str] = None,
    summary: Optional[dict] = None,
    duration_ms: Optional[int] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Best-effort append of one AI review history row.

    Args:
        doc_id: Managed document id (review target).
        scope: One of :data:`VALID_SCOPES` (not enforced).
        issue_count: Number of issues merged into the review result.
        spec_id: Spec document id the review was run against (``None``
            when no spec was bound and only builtin + LLM checks ran).
        model: LLM model identifier reported by the client (``None`` when
            the review ran rule-only, ``use_llm=False``).
        summary: Optional small summary dict (e.g. severity counts);
            JSON-serialized here (``ensure_ascii=False``).
        duration_ms: Wall-clock duration of the review call.
        prompt_tokens / completion_tokens: LLM usage when available.
        conn: Caller's connection. ``None`` → resolve the global
            ``get_database()`` connection at call time.

    Never raises: any failure is swallowed and logged at debug level —
    history must never break the review that produced it.
    """
    try:
        if conn is None:
            from backend.data.database import get_database

            conn = get_database().get_connection()
        summary_json: Optional[str] = None
        if summary is not None:
            summary_json = json.dumps(summary, ensure_ascii=False)
        conn.execute(
            "INSERT INTO office_ai_reviews "
            "(doc_id, spec_id, model, scope, issue_count, summary, "
            "duration_ms, prompt_tokens, completion_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                doc_id,
                spec_id,
                model,
                scope,
                int(issue_count),
                summary_json,
                duration_ms,
                prompt_tokens,
                completion_tokens,
                int(time.time() * 1000),
            ),
        )
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort 历史，绝不打断调用方
        logger.debug(
            "office_ai_reviews: record(doc_id=%s, scope=%s) skipped: %s",
            doc_id,
            scope,
            type(exc).__name__,
        )


def list_for_document(
    conn: sqlite3.Connection,
    doc_id: str,
    limit: int = 50,
) -> List[dict]:
    """AI review history rows for ``doc_id``, newest first.

    Returns:
        List of ``{id, doc_id, spec_id, model, scope, issue_count, summary,
        duration_ms, prompt_tokens, completion_tokens, created_at}`` dicts;
        ``summary`` is the deserialized dict (or ``None`` when
        absent/unparseable), ``created_at`` is the ms epoch. Column access
        is positional so both raw ``sqlite3.Connection`` and the
        row-factory-backed Database proxy work.
    """
    rows = conn.execute(
        "SELECT id, doc_id, spec_id, model, scope, issue_count, summary, "
        "duration_ms, prompt_tokens, completion_tokens, created_at "
        "FROM office_ai_reviews WHERE doc_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (doc_id, limit),
    ).fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        raw_summary = row[6]
        summary: Any = None
        if raw_summary is not None:
            try:
                summary = json.loads(raw_summary)
            except (TypeError, ValueError):
                summary = None
        items.append(
            {
                "id": row[0],
                "doc_id": row[1],
                "spec_id": row[2],
                "model": row[3],
                "scope": row[4],
                "issue_count": int(row[5] or 0),
                "summary": summary,
                "duration_ms": row[7],
                "prompt_tokens": row[8],
                "completion_tokens": row[9],
                "created_at": row[10],
            }
        )
    return items
