"""
文件结构摘要工具 - 提取 imports / classes / functions 骨架而非全文

设计目标: 让 agent 单次工具调用获取一个文件的"结构地图"，减少"读整文件 +
多轮 grep 找函数名"的开销。

- Python 用 ast.parse 精确提取（标准库，无新依赖）
- JS/TS 用正则提取顶层 exports（不引入 tree-sitter）
- 其他语言退化为文件头 30 行 + 行数统计
- READ 操作：不做 workspace 边界强制（与 ReadFileTool / GrepSearchTool 一致）
- 复用 file_tool 的二进制嗅探 + BOM 识别
- 错误走 ToolResult(success=False)，execute 永不抛异常
"""

from __future__ import annotations

import ast
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema
from .file_tool import MAX_READ_SIZE_BYTES, _contains_binary_marker, detect_bom_encoding

logger = logging.getLogger(__name__)

#: 不支持的语言时返回的文件头行数
FILE_SUMMARY_HEAD_LINES = 30

# ---- JS/TS 正则（顶层声明，编译一次复用）----
_JS_CLASS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)",
    re.MULTILINE,
)
_JS_FUNC_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+\*?\s*(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)
_JS_ARROW_CONST_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>",
    re.MULTILINE,
)


def _parse_python(text: str) -> Dict[str, Any]:
    """用 ast.parse 提取 Python 文件的 imports / classes / functions。

    返回结构:
        {
            "imports": ["os", "from pathlib import Path"],
            "classes": [{"name": "Foo", "line": 10, "methods": ["__init__", "bar"]}],
            "functions": [{"name": "baz", "line": 20, "params": ["a", "b"]}],
        }

    语法错误时返回空结构 + error 字段（不抛异常，整体 ToolResult 仍 success=True）。
    """
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return {
            "imports": [],
            "classes": [],
            "functions": [],
            "error": f"Python 语法错误: {e}",
        }

    imports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(a.name for a in node.names)
            imports.append(f"from {module} import {names}")
        elif isinstance(node, ast.ClassDef):
            methods = [
                n.name
                for n in ast.iter_child_nodes(node)
                if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            classes.append({
                "name": node.name,
                "line": node.lineno,
                "methods": methods,
            })
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            params = [arg.arg for arg in node.args.args]
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "params": params,
            })

    return {"imports": imports, "classes": classes, "functions": functions}


def _parse_js_ts(text: str) -> Dict[str, Any]:
    """用正则提取 JS/TS 文件的顶层 exports/classes/functions。

    不追求完整 AST 语义，只提取"地图"供 agent 导航。
    JS/TS 的 import 语句需要 module specifier 解析，正则难以准确覆盖，
    故 imports 字段留空（agent 需要时自行 grep 'import '）。
    """
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []

    for m in _JS_CLASS_RE.finditer(text):
        classes.append({
            "name": m.group(1),
            "line": text.count("\n", 0, m.start()) + 1,
            "methods": [],
        })

    for m in _JS_FUNC_RE.finditer(text):
        params = [p.strip() for p in m.group(2).split(",") if p.strip()]
        functions.append({
            "name": m.group(1),
            "line": text.count("\n", 0, m.start()) + 1,
            "params": params,
        })

    for m in _JS_ARROW_CONST_RE.finditer(text):
        functions.append({
            "name": m.group(1),
            "line": text.count("\n", 0, m.start()) + 1,
            "params": [],
        })

    return {
        "imports": [],
        "classes": classes,
        "functions": functions,
    }


def _fallback_head(text: str, total_lines: int) -> Dict[str, Any]:
    """不支持的语言退化为文件头 N 行 + 行数统计。"""
    head = "\n".join(text.splitlines()[:FILE_SUMMARY_HEAD_LINES])
    return {
        "imports": [],
        "classes": [],
        "functions": [],
        "head": head,
    }


def _detect_language(path: str, hint: Optional[str]) -> str:
    """检测文件语言：显式 hint 优先；否则按后缀映射；未知后缀返回 'unknown'。"""
    if hint:
        return hint.lower()
    ext = Path(path).suffix.lower()
    return {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".mts": "typescript",
        ".cts": "typescript",
    }.get(ext, "unknown")


class FileSummaryTool(BaseTool):
    """文件结构摘要工具"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="file_summary",
            description=(
                "提取文件的结构骨架（imports / classes / functions / methods）"
                "而不是完整内容，用于快速理解大文件的结构。"
                "Python 用 ast.parse 精确提取；JS/TS 用正则提取 exports；"
                "其他语言退化为文件头 30 行 + 行数统计。"
                "不做 workspace 边界检查（READ 操作）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（绝对或相对）",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "typescript"],
                        "description": "语言提示（可选，缺省按文件后缀自动检测）",
                    },
                },
                "required": ["path"],
            },
        )

    def _validate_file(self, path: str) -> tuple[Path, int, str]:
        """验证文件路径并返回 (file_path, original_bytes, encoding)，失败抛 ValueError"""
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path 不能为空")

        file_path = Path(path).expanduser()
        if not file_path.exists():
            raise ValueError(f"文件不存在: {path}")
        if not file_path.is_file():
            raise ValueError(f"不是文件: {path}")
        if not os.access(file_path, os.R_OK):
            raise ValueError("无读取权限")

        original_bytes = file_path.stat().st_size
        if original_bytes > MAX_READ_SIZE_BYTES:
            raise ValueError(
                f"file_too_large: 文件大小 {original_bytes} 字节超过上限 "
                f"{MAX_READ_SIZE_BYTES} 字节 (5 MiB)，无法提取摘要"
            )
        if _contains_binary_marker(file_path):
            raise ValueError("binary_file: 二进制文件不支持结构提取")

        encoding = detect_bom_encoding(file_path) or "utf-8"
        return file_path, original_bytes, encoding

    def execute(self, path: str, language: Optional[str] = None, **kwargs) -> ToolResult:
        """
        提取文件结构摘要

        Args:
            path:     文件路径
            language: 语言提示（可选）

        Returns:
            ToolResult；content 含 path / language / total_lines / original_bytes /
            imports / classes / functions / (可选) head / (可选) error。
        """
        try:
            # FIX-2 模式：未知参数 → 干净错误（避免 LLM 拼错被 **kwargs 静默吞掉）
            if kwargs:
                names = ", ".join(sorted(kwargs))
                return ToolResult(
                    success=False,
                    error=f"未知参数: {names}（合法参数: path, language）",
                )

            # 验证文件
            try:
                file_path, original_bytes, encoding = self._validate_file(path)
            except ValueError as e:
                return ToolResult(success=False, error=str(e))

            # 读取文件内容
            try:
                text = file_path.read_text(encoding=encoding, errors="replace")
            except (OSError, UnicodeError) as e:
                return ToolResult(success=False, error=f"读取失败: {e}")

            total_lines = text.count("\n") + (0 if text.endswith("\n") else 1)
            if text == "":
                total_lines = 0

            detected = _detect_language(path, language)
            summary: Dict[str, Any] = {
                "path": str(file_path.resolve()),
                "language": detected,
                "total_lines": total_lines,
                "original_bytes": original_bytes,
            }

            if detected == "python":
                parsed = _parse_python(text)
            elif detected in ("javascript", "typescript"):
                parsed = _parse_js_ts(text)
            else:
                parsed = _fallback_head(text, total_lines)

            summary.update(parsed)
            return ToolResult(success=True, content=summary)

        except Exception as e:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("file_summary 执行失败: %s", e)
            return ToolResult(success=False, error=f"提取失败: {e}")
