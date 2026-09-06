"""symbol_search 工具 —— 代码库符号索引（对标增强 Phase-2 G4 务实版）。

方案原设想的 embedding 语义索引需要 hnsw 向量库 + 增量索引器（docs/plans
§2.1 标注"工作量最大"）。本工具先交付同目标（"按概念找代码"）的零依赖
版本：stdlib ``ast`` 提取 Python 符号（类/函数/方法），构建内存倒排索引
（符号名 → 定义位置），支持子串/分词匹配。

- 只扫 ``policy.workspace_root`` 下的 ``*.py``（遵循 EXCLUDED_DIRS 排除
  重目录，同 checkpoint 口径）；每次调用现扫现查 —— 代码库 <1k 文件时
  亚秒级完成，不做持久化缓存（缓存失效与增量留待有实证需求再做）。
- READ 风险。Node/TS 符号索引后续按需追加（需正则启发式，非本版范围）。
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .checkpoint_tool import EXCLUDED_DIRS

logger = logging.getLogger(__name__)

#: 单次索引扫描的文件数上限（防御性：超大仓库不让单次调用跑几分钟）
MAX_INDEX_FILES = 2000

#: 返回结果数上限
MAX_RESULTS = 30

#: 文件大小上限（超过跳过 —— 生成文件/锁文件没有索引价值）
_MAX_SOURCE_BYTES = 512 * 1024

_CAMEL_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


@dataclass
class _Symbol:
    name: str
    kind: str  # class | function | method
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


def _iter_python_files(root: Path):
    for current_dir, dir_names, file_names in os.walk(root):
        dir_names[:] = [d for d in dir_names if d not in EXCLUDED_DIRS and not d.startswith(".")]
        for file_name in sorted(file_names):
            if file_name.endswith((".py", ".pyw")):
                yield Path(current_dir) / file_name


class SymbolSearchTool(BaseTool):
    """在工作区 Python 代码中按名称/概念搜索类与函数定义。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="symbol_search",
            description=(
                "按名称或概念搜索工作区 Python 代码的类/函数/方法定义"
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

        symbols: List[_Symbol] = []
        scanned = 0
        for file_path in _iter_python_files(root_path):
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
            symbols.extend(_extract_symbols(source, rel_path))

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
            },
        )


__all__ = ["SymbolSearchTool", "MAX_RESULTS"]
