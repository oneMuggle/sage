# backend/tools/workspace_index.py
"""F2 (round5 批次 E): 工作区语义索引 v1——源码分块 + embedding + 余弦检索。

存储取舍：**sqlite3 + numpy 余弦**（纯 wheel 依赖链），规避 hnswlib
（bundled/Windows 无 wheel，见 requirements-bundled.txt:7-22）与
sqlite-vec（扩展加载在打包环境的可用性风险）。v1 规模上限
（20000 块）内 numpy 全量余弦足够快。

- 索引库：``~/.sage/workspace-index/<workspace-sha1>/index.sqlite3``
  （用户级，与 checkpoint_tool 的 ~/.sage 惯例一致，不污染工作区）；
- 增量：files 表缓存 path → (mtime, size)，只重嵌变化/新增文件，
  删除已消失文件的全部块；
- embedding：复用 wiki 的 build_embed_request/parse_embed_response
  （OpenAI 兼容 /embeddings），配置取 app_settings 的
  modelSelections.embeddingModel；维度变化 → 清库重建；
- 失败语义：embedding 不可用/网络失败 → 带原因的 ToolResult（上层工具
  转成 error），索引部分成功时保留旧块。
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple  # noqa: UP035 — py3.8 纪律

import numpy as np

#: 源码扩展名白名单（v1：代码 + 文档；二进制/媒体不入索引）
INDEXED_EXTS = frozenset(
    {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".css", ".html", ".sh",
        ".md", ".markdown", ".txt", ".yaml", ".yml", ".toml", ".sql",
        ".go", ".rs", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb",
    }
)
#: 遍历剪枝（与 checkpoint_tool.EXCLUDED_DIRS 同口径 + 隐藏目录）
EXCLUDED_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".sage", ".llm-wiki"}
)
MAX_FILES = 2000
MAX_FILE_BYTES = 256 * 1024
CHUNK_LINES = 40
MAX_CHUNKS = 20_000
#: v2 语义分块：单个定义块超过该行数时内部再按滑窗切分
SEMANTIC_MAX_LINES = 80
#: 分块算法版本——与库内 meta.chunker_version 不符时全量重建
CHUNKER_VERSION = "2"


def _index_dir(workspace_root: str) -> Path:
    key = hashlib.sha1(
        os.path.normcase(os.path.abspath(workspace_root)).encode("utf-8")
    ).hexdigest()
    env = os.environ.get("SAGE_USER_DATA_DIR")
    base = Path(env) if env else Path.home() / ".sage"
    return base / "workspace-index" / key


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS files ("
        "path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT NOT NULL, "
        "start_line INTEGER NOT NULL, content TEXT NOT NULL, vector BLOB NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)"
    )
    return conn


def _iter_source_files(root: str) -> List[Path]:
    """枚举工作区源文件（剪枝 + 扩展名白名单 + 大小上限, 排序保稳定）。"""
    out: List[Path] = []
    root_path = Path(root)
    for current_dir, dir_names, file_names in os.walk(root_path):
        dir_names[:] = sorted(d for d in dir_names if d not in EXCLUDED_DIRS and not d.startswith("."))
        for name in sorted(file_names):
            path = Path(current_dir) / name
            if path.suffix.lower() not in INDEXED_EXTS:
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            out.append(path)
            if len(out) >= MAX_FILES:
                return out
    return out


def chunk_file_lines(lines: List[str], chunk_lines: int = CHUNK_LINES) -> List[Tuple[int, str]]:
    """按 ``chunk_lines`` 滑窗切块, 返回 [(start_line_1based, text)]。"""
    chunks: List[Tuple[int, str]] = []
    step = max(1, int(chunk_lines * 0.75))  # 25% 重叠保上下文
    total = len(lines)
    start = 0
    while start < total:
        end = min(total, start + chunk_lines)
        text = "\n".join(lines[start:end]).strip()
        if text:
            chunks.append((start + 1, text))
        if end >= total:
            break
        start += step
    return chunks


# ---------- v2: 顶层定义边界分块 ----------

#: 语言族 → 顶层定义起始行正则（无缩进才算，保守起步避免误报切碎正文）
_SEMANTIC_BOUNDARY_RES: Dict[str, re.Pattern] = {
    "py": re.compile(r"(?:async\s+def|def|class)\s"),
    "js": re.compile(r"(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(?:async\s+)?(?:function\s|class\s|interface\s|type\s|enum\s)"),
    "go": re.compile(r"(?:func\s|type\s+\w+\s+(?:struct|interface)\b)"),
    "rs": re.compile(r"(?:pub\s+)?(?:async\s+)?(?:fn\s|struct\s|trait\s|enum\s|impl\s)"),
    "clike": re.compile(r"^(?:public|private|protected|internal|static|final|sealed|abstract)\s.*\b(?:class|interface|enum)\s"),
    "rb": re.compile(r"(?:def\s|class\s)"),
}

#: 扩展名 → 语言族（不在表内的扩展回退 v1 滑窗）
_EXT_LANG_FAMILY: Dict[str, str] = {
    ".py": "py",
    ".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
    ".mjs": "js", ".cjs": "js",
    ".go": "go",
    ".rs": "rs",
    ".java": "clike", ".cs": "clike",
    ".rb": "rb",
}


def _semantic_boundaries(lines: List[str], family: str) -> List[int]:
    """收集顶层定义的起始行下标（0-based）。装饰器行回溯并入定义。"""
    regex = _SEMANTIC_BOUNDARY_RES[family]
    bounds: List[int] = []
    for idx, line in enumerate(lines):
        if not line or line[0] in " \t)":
            # 顶层定义不允许缩进；')' 开头的行是折行续体，跳过
            continue
        if not regex.search(line):
            continue
        if family == "clike" and not regex.match(line):
            # clike 正则锚定行首修饰符,双保险
            continue
        # py 分支: 连续的顶层装饰器行并入定义起点
        if family == "py":
            start = idx
            while (
                start > 0
                and lines[start - 1].startswith("@")
                and not lines[start - 1][:1].isspace()
            ):
                start -= 1
            bounds.append(start)
        else:
            bounds.append(idx)
    return bounds


def _sliding_slices(length: int, window: int, offset: int) -> List[Tuple[int, int]]:
    """相对 [offset, length) 区间产出滑窗 (start, end) 切片，尾窗不重叠。"""
    step = max(1, int(window * 0.75))
    out: List[Tuple[int, int]] = []
    start = offset
    while start < length:
        end = min(length, start + window)
        out.append((start, end))
        if end >= length:
            break
        start += step
    return out


def chunk_file_semantic(
    lines: List[str], family: str, chunk_lines: int = CHUNK_LINES
) -> List[Tuple[int, str]]:
    """按顶层定义切块：定义块整块成 chunk，超长块内部滑窗，无定义回退滑窗。

    返回 [(start_line_1based, text)]，与 ``chunk_file_lines`` 同形。
    """
    bounds = _semantic_boundaries(lines, family)
    if not bounds:
        return chunk_file_lines(lines, chunk_lines)

    chunks: List[Tuple[int, str]] = []

    def _emit(start: int, end: int) -> None:
        for s, e in _sliding_slices(end, chunk_lines, start):
            text = "\n".join(lines[s:e]).strip()
            if text:
                chunks.append((s + 1, text))

    # 前导区（imports/模块注释）滑窗切块
    _emit(0, bounds[0])
    for i, bound in enumerate(bounds):
        block_end = bounds[i + 1] if i + 1 < len(bounds) else len(lines)
        if block_end - bound <= SEMANTIC_MAX_LINES:
            text = "\n".join(lines[bound:block_end]).strip()
            if text:
                chunks.append((bound + 1, text))
        else:
            _emit(bound, block_end)
    return chunks


def chunk_file(path: Path, lines: List[str]) -> List[Tuple[int, str]]:
    """按扩展名分派 v2 语义分块 / v1 滑窗。"""
    family = _EXT_LANG_FAMILY.get(path.suffix.lower())
    if family is None:
        return chunk_file_lines(lines)
    return chunk_file_semantic(lines, family)


def load_embedding_config() -> Optional[Dict[str, str]]:
    """从 app_settings 读取 embedding 端点配置; 未配置返回 None。

    前端 modelSelections.embeddingModel = {endpointId, modelId} 指向
    endpoints 数组中的条目（OpenAI 兼容 /embeddings）。
    """
    from backend.data.settings_repo import SettingsRepository

    raw = SettingsRepository().get_json("app_settings")
    if not isinstance(raw, dict):
        return None
    selection = (raw.get("modelSelections") or {}).get("embeddingModel") or {}
    endpoint_id = selection.get("endpointId")
    model_id = selection.get("modelId")
    if not endpoint_id or not model_id:
        return None
    for ep in raw.get("endpoints") or []:
        if isinstance(ep, dict) and ep.get("id") == endpoint_id:
            base_url = ep.get("baseUrl")
            if not base_url:
                return None
            return {"base_url": base_url, "api_key": ep.get("apiKey") or "", "model": model_id}
    return None


def _embed_texts(config: Dict[str, str], texts: List[str]) -> List[List[float]]:
    """调用 OpenAI 兼容 /embeddings。测试可 monkeypatch 本函数注入假向量。"""
    import httpx

    from backend.wiki.embeddings import build_embed_request, parse_embed_response

    embed_config = {
        "base_url": config["base_url"],
        "api_key": config["api_key"],
        "model": config["model"],
    }
    vectors: List[List[float]] = []
    # 分批（每批 32 条）避免超大请求体
    for i in range(0, len(texts), 32):
        batch = texts[i : i + 32]
        request = build_embed_request(
            type("C", (), {**embed_config, "dim": 0})(),  # 兼容 build_embed_request 的属性访问
            batch,
        )
        response = httpx.post(
            request.url,
            json=request.body,
            headers=request.headers,
            timeout=60.0,
        )
        response.raise_for_status()
        vectors.extend(parse_embed_response(response.json()))
    return vectors


def _meta_get(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row[0]


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _index_workspace(root: str, config: Dict[str, str]) -> Dict[str, Any]:
    """增量索引工作区。返回 {indexed, skipped_chunks, dim}。"""
    db_path = _index_dir(root) / "index.sqlite3"
    conn = _connect(db_path)
    try:
        stored_dim = _meta_get(conn, "dim")
        # 先嵌入一个探针确定维度; 与库内 dim 不符 → 清库重建
        probe = _embed_texts(config, ["dim probe"])
        dim = len(probe[0])
        stored_chunker = _meta_get(conn, "chunker_version")
        if (stored_dim is not None and int(stored_dim) != dim) or (
            stored_chunker is not None and stored_chunker != CHUNKER_VERSION
        ):
            # chunker 版本变更（v1 滑窗 → v2 语义分块）同样全量重建
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM files")
        _meta_set(conn, "dim", str(dim))
        _meta_set(conn, "chunker_version", CHUNKER_VERSION)

        known: Dict[str, Tuple[float, int]] = {
            row[0]: (row[1], row[2])
            for row in conn.execute("SELECT path, mtime, size FROM files")
        }
        files = _iter_source_files(root)
        to_index: List[Tuple[Path, List[Tuple[int, str]]]] = []
        current: Dict[str, Tuple[float, int]] = {}
        for path in files:
            rel = os.path.relpath(path, root).replace("\\", "/")
            stat = path.stat()
            current[rel] = (stat.st_mtime, stat.st_size)
            if rel in known and known[rel] == (stat.st_mtime, stat.st_size):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            chunks = chunk_file(path, lines)
            if chunks:
                to_index.append((path, chunks))

        indexed = 0
        for path, file_chunks in to_index:
            rel = os.path.relpath(path, root).replace("\\", "/")
            mtime, size = current[rel]
            conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            texts = [text for _, text in file_chunks]
            capped_chunks = file_chunks
            if len(texts) > 256:  # 单文件嵌入分批上限保护
                texts = texts[:256]
                capped_chunks = file_chunks[:256]
            vectors = _embed_texts(config, texts)
            for (start_line, text), vector in zip(  # noqa: B905 — py3.8 无 strict（#487）
                capped_chunks, vectors
            ):
                if not vector:
                    continue
                conn.execute(
                    "INSERT INTO chunks (path, start_line, content, vector) VALUES (?, ?, ?, ?)",
                    (rel, start_line, text, np.asarray(vector, dtype=np.float32).tobytes()),
                )
            conn.execute(
                "INSERT INTO files (path, mtime, size) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size",
                (rel, mtime, size),
            )
            indexed += 1

        # 清理已消失文件
        gone = [p for p in known if p not in current]
        for rel in gone:
            conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
            conn.execute("DELETE FROM files WHERE path = ?", (rel,))
        conn.commit()
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"indexed": indexed, "chunks": chunk_count, "dim": dim}
    finally:
        conn.close()


def _search_workspace(
    root: str, config: Dict[str, str], query: str, limit: int
) -> List[Dict[str, Any]]:
    db_path = _index_dir(root) / "index.sqlite3"
    if not db_path.is_file():
        return []
    query_vector = np.asarray(_embed_texts(config, [query])[0], dtype=np.float32)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT path, start_line, content, vector FROM chunks"
        ).fetchall()
        if not rows:
            return []
        matrix = np.frombuffer(b"".join(r[3] for r in rows), dtype=np.float32).reshape(
            len(rows), -1
        )
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query_vector)
        norms[norms == 0] = 1e-9
        scores = (matrix @ query_vector) / norms
        top = np.argsort(-scores)[:limit]
        results: List[Dict[str, Any]] = []
        for i in top:
            if scores[i] <= 0:
                continue
            path, start_line, content, _ = rows[i]
            snippet = content[:400]
            results.append(
                {
                    "path": path,
                    "start_line": int(start_line),
                    "score": round(float(scores[i]), 4),
                    "snippet": snippet,
                }
            )
        return results
    finally:
        conn.close()


def workspace_index_stats(root: str) -> Dict[str, Any]:
    """索引统计（供工具在未配置 embedding 时给出引导信息）。"""
    db_path = _index_dir(root) / "index.sqlite3"
    if not db_path.is_file():
        return {"indexed_files": 0, "chunks": 0}
    conn = sqlite3.connect(str(db_path))
    try:
        files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {"indexed_files": files, "chunks": chunks}
    except sqlite3.Error:
        return {"indexed_files": 0, "chunks": 0}
    finally:
        conn.close()
