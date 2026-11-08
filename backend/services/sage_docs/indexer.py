# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""Sage 内置文档索引（sage-guide 知识源）。

索引库：``~/.sage/sage-docs-index/index.sqlite3``（可用
``SAGE_DOCS_INDEX_DIR`` 覆盖，测试隔离用）。

表结构::

    docs_meta(rel_path PK, mtime_ns, size, sha1)
    chunks(rel_path, chunk_index, heading, start_line, content)
    chunks_fts(rel_path UNINDEXED, chunk_index UNINDEXED, content_tok)

``content_tok`` 是 jieba 空格分词后的文本：FTS5 的 unicode61 分词器
不切中文，必须预分词（查询侧对应 ``tokenize_for_search``）。

增量策略：``(mtime_ns, size)`` 未变则跳过该文件；变了才重新读取、
重算 sha1、删旧块重写。文件消失则清索引。首次检索前惰性构建，
构建过程持模块级锁。
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from backend.memory.chinese_tokenizer import tokenize
from backend.services.sage_docs.paths import iter_doc_files, resolve_index_dir

logger = logging.getLogger(__name__)

DB_FILENAME = "index.sqlite3"

#: 单块最大字符数；超出按段落二次切分。
MAX_CHUNK_CHARS = 1200
#: 二次切分时相邻块的重叠字符数，避免答案被截断在边界。
CHUNK_OVERLAP_CHARS = 100

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BUILD_LOCK = threading.Lock()

_SCHEMA_STATEMENTS: Tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS docs_meta ("
    "rel_path TEXT PRIMARY KEY, mtime_ns INTEGER NOT NULL, "
    "size INTEGER NOT NULL, sha1 TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS chunks ("
    "rel_path TEXT NOT NULL, chunk_index INTEGER NOT NULL, "
    "heading TEXT NOT NULL DEFAULT '', start_line INTEGER NOT NULL, "
    "content TEXT NOT NULL, PRIMARY KEY(rel_path, chunk_index))",
    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
    "rel_path UNINDEXED, chunk_index UNINDEXED, content_tok)",
)


@dataclass(frozen=True)
class DocChunk:
    """一个可检索的文档片段。"""

    heading: str
    start_line: int
    content: str


def _split_oversized(heading: str, start_line: int, content: str) -> List[DocChunk]:
    """超长段落按 ``MAX_CHUNK_CHARS`` 二次切分，带少量重叠。"""
    if len(content) <= MAX_CHUNK_CHARS:
        return [DocChunk(heading, start_line, content)]

    pieces: List[DocChunk] = []
    buffer = ""
    buffer_start = start_line
    cursor = start_line
    for paragraph in content.split("\n\n"):
        if buffer and len(buffer) + len(paragraph) + 2 > MAX_CHUNK_CHARS:
            pieces.append(DocChunk(heading, buffer_start, buffer.strip()))
            buffer = buffer[-CHUNK_OVERLAP_CHARS:] + "\n\n" + paragraph
            buffer_start = cursor
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        cursor += paragraph.count("\n") + 2
    if buffer.strip():
        pieces.append(DocChunk(heading, buffer_start, buffer.strip()))
    return pieces


def chunk_markdown(text: str) -> List[DocChunk]:
    """按 Markdown 标题切块；标题链形如 ``顶层 › 二级``。"""
    chunks: List[DocChunk] = []
    heading_stack: List[Tuple[int, str]] = []
    buffer_lines: List[str] = []
    buffer_heading = ""
    buffer_start = 1

    def flush() -> None:
        content = "\n".join(buffer_lines).strip()
        if content:
            chunks.extend(_split_oversized(buffer_heading, buffer_start, content))

    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _HEADING_RE.match(line)
        if not match:
            buffer_lines.append(line)
            continue
        flush()
        level = len(match.group(1))
        title = match.group(2).strip()
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))
        buffer_heading = " › ".join(item for _, item in heading_stack)
        buffer_start = lineno
        buffer_lines = [line]

    flush()
    return chunks


def _ensure_schema(conn: sqlite3.Connection) -> None:
    for statement in _SCHEMA_STATEMENTS:
        conn.execute(statement)


def connect_index(index_dir: Optional[Path] = None) -> sqlite3.Connection:
    """打开（必要时创建）索引库；FTS5 不可用时抛 ``sqlite3.OperationalError``。"""
    directory = index_dir or resolve_index_dir()
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(directory / DB_FILENAME))
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _delete_doc(conn: sqlite3.Connection, rel_path: str) -> None:
    conn.execute("DELETE FROM chunks WHERE rel_path = ?", (rel_path,))
    conn.execute("DELETE FROM chunks_fts WHERE rel_path = ?", (rel_path,))


def _existing_fingerprints(conn: sqlite3.Connection) -> Dict[str, Tuple[int, int, str]]:
    rows = conn.execute("SELECT rel_path, mtime_ns, size, sha1 FROM docs_meta").fetchall()
    return {row[0]: (int(row[1]), int(row[2]), str(row[3])) for row in rows}


def _reindex_doc(conn: sqlite3.Connection, docs_root: Path, rel_path: str) -> int:
    path = docs_root / rel_path
    stat = path.stat()
    text = path.read_text(encoding="utf-8", errors="replace")
    sha1 = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()
    _delete_doc(conn, rel_path)
    chunks = chunk_markdown(text)
    for index, chunk in enumerate(chunks):
        conn.execute(
            "INSERT INTO chunks (rel_path, chunk_index, heading, start_line, content) "
            "VALUES (?, ?, ?, ?, ?)",
            (rel_path, index, chunk.heading, chunk.start_line, chunk.content),
        )
        conn.execute(
            "INSERT INTO chunks_fts (rel_path, chunk_index, content_tok) VALUES (?, ?, ?)",
            (rel_path, index, tokenize(f"{chunk.heading}\n{chunk.content}")),
        )
    conn.execute(
        "INSERT OR REPLACE INTO docs_meta (rel_path, mtime_ns, size, sha1) VALUES (?, ?, ?, ?)",
        (rel_path, stat.st_mtime_ns, stat.st_size, sha1),
    )
    return len(chunks)


def _sync_index(conn: sqlite3.Connection, docs_root: Path, *, force: bool) -> Dict[str, int]:
    existing = _existing_fingerprints(conn)
    seen: Set[str] = set()
    reindexed = 0
    total_chunks = 0

    for path in iter_doc_files(docs_root):
        rel_path = path.relative_to(docs_root).as_posix()
        try:
            stat = path.stat()
        except OSError:
            continue
        seen.add(rel_path)
        previous = existing.get(rel_path)
        unchanged = (
            previous is not None
            and previous[0] == stat.st_mtime_ns
            and previous[1] == stat.st_size
        )
        if unchanged and not force:
            continue
        try:
            total_chunks += _reindex_doc(conn, docs_root, rel_path)
        except OSError as exc:
            logger.warning("读取 Sage 文档失败，跳过 %s: %s", rel_path, exc)
            continue
        reindexed += 1

    for rel_path in set(existing) - seen:
        _delete_doc(conn, rel_path)
        conn.execute("DELETE FROM docs_meta WHERE rel_path = ?", (rel_path,))

    conn.commit()
    return {"files": len(seen), "reindexed": reindexed, "chunks": total_chunks}


def ensure_index(
    docs_root: Path, index_dir: Optional[Path] = None, *, force: bool = False
) -> Dict[str, int]:
    """增量同步索引；返回 ``{"files", "reindexed", "chunks"}``。

    并发安全：模块级锁串行化构建。失败向上抛 ``sqlite3.Error``，
    由检索层 fail-open 处理。
    """
    with _BUILD_LOCK:
        conn = connect_index(index_dir)
        try:
            return _sync_index(conn, docs_root, force=force)
        finally:
            conn.close()


def count_chunks(index_dir: Optional[Path] = None) -> int:
    """索引内块数（未建库 / 读取失败返回 0）。"""
    directory = index_dir or resolve_index_dir()
    db_path = directory / DB_FILENAME
    if not db_path.is_file():
        return 0
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0
