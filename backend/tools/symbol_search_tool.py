"""symbol_search 工具 —— 代码库符号索引（对标增强 Phase-2 G4 务实版）。

方案原设想的 embedding 语义索引需要 hnsw 向量库 + 增量索引器（docs/plans
§2.1 标注"工作量最大"）。本工具先交付同目标（"按概念找代码"）的零依赖
版本：Python 走 stdlib ``ast``、JS/TS/Go/Rust/Java 走行级正则提取符号
（类/函数/方法/接口），支持子串/分词匹配。

- 只扫 ``policy.workspace_root`` 下的源码文件（遵循 EXCLUDED_DIRS 排除
  重目录，同 checkpoint 口径）；
- H-1 (round5 批次 H): 符号持久化缓存于
  ``~/.sage/symbol-index/<workspace-sha1>/index.sqlite3``——
  files 表记 mtime/size，增量只重析变化文件，消失文件清理；
  缓存打不开时 fail-open 退回全量内存扫描；
- READ 风险。
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .checkpoint_tool import EXCLUDED_DIRS

logger = logging.getLogger(__name__)

#: 单次索引扫描的文件数上限（防御性：超大仓库不让单次调用跑几分钟）
MAX_INDEX_FILES = 5000

#: 返回结果数上限
MAX_RESULTS = 30

#: 文件大小上限（超过跳过 —— 生成文件/锁文件没有索引价值）
_MAX_SOURCE_BYTES = 512 * 1024

_CAMEL_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")

#: 可索引扩展名（Python + JS/TS + F-3/H-2 扩展的 Go/Rust/Java）
_INDEXABLE_SUFFIXES = (
    ".py", ".pyw",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java",
)


@dataclass
class _Symbol:
    name: str
    kind: str  # class | function | method | interface | type
    path: str
    line: int
    tokens: List[str] = field(default_factory=list)


def _tokenize(name: str) -> List[str]:
    """snake_case / camelCase 拆词（用于概念匹配）。"""
    parts = name.replace("-", "_").split("_")
    tokens: List[str] = []
    for part in parts:
        tokens.extend(match.group(0).lower() for match in _CAMEL_SPLIT.finditer(part))
    return [t for t in tokens if len(t) >= 3] or [t.lower() for t in parts if t]


def _extract_symbols(source: str, rel_path: str) -> List[_Symbol]:
    """AST 提取顶层类/函数与类内方法。"""
    symbols: List[_Symbol] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []  # 语法坏文件跳过（诊断属 G8 职责）
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):  # noqa: UP038 — py3.8 兼容
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            symbols.append(
                _Symbol(node.name, kind, rel_path, node.lineno, _tokenize(node.name))
            )
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):  # noqa: UP038 — py3.8 兼容
                    symbols.append(
                        _Symbol(
                            f"{node.name}.{child.name}",
                            "method",
                            rel_path,
                            child.lineno,
                            _tokenize(child.name),
                        )
                    )
    return symbols


def _iter_indexable_files(root: Path):
    for current_dir, dir_names, file_names in os.walk(root):
        dir_names[:] = [d for d in dir_names if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for file_name in sorted(file_names):
            if file_name.endswith(_INDEXABLE_SUFFIXES):
                yield Path(current_dir) / file_name


def _extract_symbols_for(path: Path, source: str, rel_path: str) -> List[_Symbol]:
    """按扩展名分派：Python 走 AST, JS/TS 走行级正则。"""
    if path.suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
        return _extract_js_symbols(source, rel_path)
    if path.suffix in (".go", ".rs", ".java"):
        return _extract_go_rs_java_symbols(source, rel_path)
    return _extract_symbols(source, rel_path)


# F-3 (round5 批次 F): JS/TS 顶层定义提取（行级正则, v1 覆盖常见形态）。
_JS_FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+([A-Za-z_$][\w$]*)"
)
_JS_CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"
)
_JS_CONST_ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_JS_INTERFACE_TYPE_RE = re.compile(
    r"^\s*(?:export\s+)?(interface|type)\s+([A-Za-z_$][\w$]*)"
)


def _extract_js_symbols(source: str, rel_path: str) -> List[_Symbol]:
    """JS/TS 行级正则提取（顶层 function/class/const 箭头/interface/type）。"""
    symbols: List[_Symbol] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = _JS_FUNCTION_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "function", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _JS_CLASS_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "class", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _JS_CONST_ARROW_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "function", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _JS_INTERFACE_TYPE_RE.match(line)
        if m:
            kind = "interface" if m.group(1) == "interface" else "type"
            symbols.append(_Symbol(m.group(2), kind, rel_path, lineno, _tokenize(m.group(2))))
    return symbols


# H-2 (round5 批次 H): Go / Rust / Java 行级定义提取（顶层常见形态）。
_GO_FUNC_RE = re.compile(r"^func\s+(?:\([^)]+\)\s*)?([A-Za-z_][\w]*)\(")
_GO_TYPE_RE = re.compile(r"^type\s+([A-Za-z_][\w]*)\s+(?:struct|interface)\b")
_RS_FN_RE = re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_][\w]*)")
_RS_TYPE_RE = re.compile(r"^\s*(?:pub\s+)?(?:struct|trait|enum)\s+([A-Za-z_][\w]*)")
_RS_IMPL_RE = re.compile(r"^impl(?:<[^>]*>)?\s+([A-Za-z_][\w:]*)")
_JAVA_TYPE_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+)?(?:final\s+|abstract\s+)?"
    r"(?:class|interface|enum)\s+([A-Za-z_][\w]*)"
)
_JAVA_METHOD_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+)?(?:static\s+)?[\w<>\[\],\s]+?\s+"
    r"([A-Za-z_][\w]*)\s*\([^;]*\)\s*(?:throws\s+[\w,\s]+)?\{"
)


def _extract_go_rs_java_symbols(source: str, rel_path: str) -> List[_Symbol]:
    """Go/Rust/Java 行级正则提取（顶层与类型内常见定义形态）。"""
    symbols: List[_Symbol] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = _GO_FUNC_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "function", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _GO_TYPE_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "class", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _RS_TYPE_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "class", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _RS_IMPL_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "class", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _RS_FN_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "function", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _JAVA_TYPE_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "class", rel_path, lineno, _tokenize(m.group(1))))
            continue
        m = _JAVA_METHOD_RE.match(line)
        if m:
            symbols.append(_Symbol(m.group(1), "method", rel_path, lineno, _tokenize(m.group(1))))
    return symbols


# ==================== H-1 (round5 批次 H): 持久化缓存 + 增量扫描 ====================


def _cache_db_path(workspace_root: str) -> Path:
    key = hashlib.sha1(
        os.path.normcase(os.path.abspath(workspace_root)).encode("utf-8")
    ).hexdigest()
    env = os.environ.get("SAGE_USER_DATA_DIR")
    base = Path(env) if env else Path.home() / ".sage"
    return base / "symbol-index" / key / "index.sqlite3"


def _open_cache(db_path: Path) -> Optional[sqlite3.Connection]:
    """打开缓存连接；任何失败返回 None（fail-open 走全量内存扫描）。"""
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS files ("
            "path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS symbols ("
            "path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL, "
            "line INTEGER NOT NULL, tokens_json TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path)"
        )
        return conn
    except sqlite3.Error:
        return None


def _load_cached_symbols(conn: sqlite3.Connection) -> List[_Symbol]:
    symbols: List[_Symbol] = []
    for path, name, kind, line, tokens_json in conn.execute(
        "SELECT path, name, kind, line, tokens_json FROM symbols"
    ):
        try:
            tokens = json.loads(tokens_json)
        except ValueError:
            tokens = []
        symbols.append(_Symbol(name, kind, path, line, tokens))
    return symbols


def _reindex_incremental(
    conn: sqlite3.Connection, root_path: Path
) -> Tuple[List[_Symbol], int]:
    """增量重析：变化/新增文件重提取, 消失文件清理。

    返回 (全量符号列表, 本次重析文件数)。sqlite 失败由调用方 fail-open。
    """
    known: Dict[str, Tuple[float, int]] = {
        row[0]: (row[1], row[2])
        for row in conn.execute("SELECT path, mtime, size FROM files")
    }
    current: Dict[str, Tuple[float, int, List[_Symbol]]] = {}
    scanned = 0
    for file_path in _iter_indexable_files(root_path):
        if scanned >= MAX_INDEX_FILES:
            break
        try:
            stat = file_path.stat()
            if stat.st_size > _MAX_SOURCE_BYTES:
                continue
            rel_path = file_path.relative_to(root_path).as_posix()
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        current[rel_path] = (stat.st_mtime, stat.st_size, [])
        # 变化/新增文件才重提取（提取结果先挂在临时结构外, 统一落库）
        if rel_path in known and known[rel_path] == (stat.st_mtime, stat.st_size):
            continue
        current[rel_path] = (
            stat.st_mtime,
            stat.st_size,
            _extract_symbols_for(file_path, source, rel_path),
        )

    changed: List[str] = []
    for rel_path, (mtime, size, symbols) in current.items():
        if rel_path in known and known[rel_path] == (mtime, size) and not symbols:
            continue  # 未变化且缓存无显式符号行 → 跳过落库
        if rel_path in known and known[rel_path] == (mtime, size):
            continue
        changed.append(rel_path)

    # 落库：变化文件替换符号行, 消失文件删行
    for rel_path in changed:
        conn.execute("DELETE FROM symbols WHERE path = ?", (rel_path,))
        for symbol in current[rel_path][2]:
            conn.execute(
                "INSERT INTO symbols (path, name, kind, line, tokens_json) VALUES (?, ?, ?, ?, ?)",
                (
                    rel_path,
                    symbol.name,
                    symbol.kind,
                    symbol.line,
                    json.dumps(symbol.tokens),
                ),
            )
        mtime, size, _ = current[rel_path]
        conn.execute(
            "INSERT INTO files (path, mtime, size) VALUES (?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size",
            (rel_path, mtime, size),
        )
    gone = [p for p in known if p not in current]
    for rel_path in gone:
        conn.execute("DELETE FROM symbols WHERE path = ?", (rel_path,))
        conn.execute("DELETE FROM files WHERE path = ?", (rel_path,))
    conn.commit()

    # 未变化文件从缓存读回符号, 与本次重析的合并成全量
    symbols = _load_cached_symbols(conn)
    return symbols, len(changed)


class SymbolSearchTool(BaseTool):
    """在工作区 Python/JS/TS/Go/Rust/Java 代码中按名称/概念搜索定义。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="symbol_search",
            description=(
                "按名称或概念搜索工作区 Python/JS/TS/Go/Rust/Java 代码的"
                "类/函数/方法/接口定义"
                "（如搜 'checkpoint' 找快照相关实现，搜 'kill process' "
                "匹配 kill_process_tree）。比 grep 精准 —— 只返回定义处，"
                "不含调用与注释噪音。返回限定定义文件与行号。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "符号名或概念词（空格分词 = AND 匹配）"},
                },
                "required": ["query"],
            },
        )

    def execute(self, query: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: query）",
            )
        if not isinstance(query, str) or not query.strip():
            return ToolResult(success=False, error="query 不能为空")

        root = self._policy.workspace_root
        if not root:
            return ToolResult(success=False, error="symbol_search 需要绑定工作区（workspace）")
        root_path = Path(root)
        if not root_path.is_dir():
            return ToolResult(success=False, error=f"工作区目录不存在: {root}")

        needle = query.strip().lower()
        needle_tokens = [t for t in _tokenize(needle) if t]

        # H-1: 增量缓存优先；缓存不可用 fail-open 退回全量内存扫描
        scanned = 0
        cached = False
        symbols: List[_Symbol] = []
        conn = _open_cache(_cache_db_path(root))
        if conn is not None:
            try:
                symbols, reindexed = _reindex_incremental(conn, root_path)
                cached = True
                scanned = reindexed
            except sqlite3.Error:
                logger.warning("symbol 缓存读写失败, 退回全量扫描", exc_info=True)
                cached = False
            finally:
                conn.close()
        if not cached:
            for file_path in _iter_indexable_files(root_path):
                if scanned >= MAX_INDEX_FILES:
                    break
                try:
                    if file_path.stat().st_size > _MAX_SOURCE_BYTES:
                        continue
                    source = file_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                scanned += 1
                rel_path = file_path.relative_to(root_path).as_posix()
                symbols.extend(_extract_symbols_for(file_path, source, rel_path))

        # 打分：精确名 > 前缀 > 子串 > 分词 AND 命中数
        scored: List[tuple] = []
        for symbol in symbols:
            name_lower = symbol.name.lower()
            if name_lower == needle:
                score = 100
            elif name_lower.startswith(needle):
                score = 80
            elif needle in name_lower:
                score = 60
            elif needle_tokens and all(t in symbol.tokens for t in needle_tokens):
                score = 40 + 5 * len(needle_tokens)
            elif needle_tokens and any(t in symbol.tokens for t in needle_tokens):
                score = 20 * sum(1 for t in needle_tokens if t in symbol.tokens)
            else:
                continue
            scored.append((score, symbol))

        scored.sort(key=lambda pair: (-pair[0], pair[1].path, pair[1].line))
        matches = [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "path": symbol.path,
                "line": symbol.line,
            }
            for _, symbol in scored[:MAX_RESULTS]
        ]
        return ToolResult(
            success=True,
            content={
                "query": needle,
                "matches": matches,
                "total": len(scored),
                "scanned_files": scanned,
                "truncated": len(scored) > MAX_RESULTS,
                "cached": cached,
            },
        )
