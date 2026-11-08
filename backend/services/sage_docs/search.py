# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Sage 内置文档检索（sage-guide 知识源）。

检索前先做一次增量索引同步（52 篇文档的 stat 成本可忽略）；
FTS5 不可用、索引损坏、文档目录缺失时一律 fail-open 返回空列表 ——
知识库故障绝不能让对话失败。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from backend.memory.chinese_tokenizer import tokenize_for_search
from backend.services.sage_docs.indexer import connect_index, ensure_index
from backend.services.sage_docs.paths import resolve_docs_root

logger = logging.getLogger(__name__)

#: 单次检索返回的最大块数（上限，调用方 limit 更小时以调用方为准）。
MAX_SEARCH_LIMIT = 20

_MATCH_SQL = (
    "SELECT chunks_fts.rel_path, chunks_fts.chunk_index, chunks.heading, "
    "chunks.start_line, chunks.content, bm25(chunks_fts) AS rank "
    "FROM chunks_fts "
    "JOIN chunks ON chunks.rel_path = chunks_fts.rel_path "
    "AND chunks.chunk_index = chunks_fts.chunk_index "
    "WHERE chunks_fts MATCH ? "
    "ORDER BY rank "
    "LIMIT ?"
)


@dataclass(frozen=True)
class SageDocHit:
    """一条文档检索命中。"""

    rel_path: str
    chunk_index: int
    heading: str
    start_line: int
    content: str
    score: float


def search_sage_docs(
    query: str,
    limit: int = 5,
    docs_root: Optional[Path] = None,
    index_dir: Optional[Path] = None,
) -> List[SageDocHit]:
    """检索内置文档，按 bm25 相关度降序返回。"""
    if limit <= 0:
        return []
    match_expression = tokenize_for_search(query)
    if match_expression in ("", '""'):
        return []
    limit = min(limit, MAX_SEARCH_LIMIT)

    root = docs_root or resolve_docs_root()
    if root is None:
        return []

    try:
        ensure_index(root, index_dir)
        conn = connect_index(index_dir)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("Sage 文档索引不可用，检索降级为空结果: %s", exc)
        return []

    try:
        rows = conn.execute(_MATCH_SQL, (match_expression, limit)).fetchall()
    except sqlite3.Error as exc:
        logger.warning("Sage 文档检索失败（query=%r）: %s", query, exc)
        return []
    finally:
        conn.close()

    return [
        SageDocHit(
            rel_path=str(row[0]),
            chunk_index=int(row[1]),
            heading=str(row[2]),
            start_line=int(row[3]),
            content=str(row[4]),
            score=float(row[5]),
        )
        for row in rows
    ]
