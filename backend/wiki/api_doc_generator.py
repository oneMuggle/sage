"""Coding 项目 API 文档自动生成 (2026-09-25)

项目类型分类系统 - Phase 9.5.2
从代码文件中提取函数/类签名和文档字符串，生成 API 文档骨架。

支持的语言：
- Python (.py): 从 docstring 和 type hints 提取
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class FunctionSignature:
    """函数签名信息"""

    name: str
    parameters: List[str]
    return_type: str
    docstring: str
    file_path: str
    line_number: int


@dataclass
class ClassInfo:
    """类信息"""

    name: str
    methods: List[FunctionSignature]
    docstring: str
    file_path: str
    line_number: int


@dataclass
class ModuleDoc:
    """模块文档"""

    file_path: str
    module_docstring: str
    functions: List[FunctionSignature]
    classes: List[ClassInfo]


def extract_python_module(file_path: Path) -> Optional[ModuleDoc]:
    """从 Python 文件提取文档信息。"""
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None

    module_docstring = ast.get_docstring(tree) or ""
    functions: List[FunctionSignature] = []
    classes: List[ClassInfo] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            params = []
            for arg in node.args.args:
                if arg.arg != "self":
                    annotation = ""
                    if arg.annotation:
                        annotation = ast.unparse(arg.annotation)
                    params.append(f"{arg.arg}: {annotation}" if annotation else arg.arg)

            return_type = ""
            if node.returns:
                return_type = ast.unparse(node.returns)

            functions.append(
                FunctionSignature(
                    name=node.name,
                    parameters=params,
                    return_type=return_type,
                    docstring=ast.get_docstring(node) or "",
                    file_path=str(file_path),
                    line_number=node.lineno,
                )
            )

        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods: List[FunctionSignature] = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    params = []
                    for arg in item.args.args:
                        if arg.arg != "self":
                            annotation = ""
                            if arg.annotation:
                                annotation = ast.unparse(arg.annotation)
                            params.append(
                                f"{arg.arg}: {annotation}" if annotation else arg.arg
                            )

                    return_type = ""
                    if item.returns:
                        return_type = ast.unparse(item.returns)

                    methods.append(
                        FunctionSignature(
                            name=item.name,
                            parameters=params,
                            return_type=return_type,
                            docstring=ast.get_docstring(item) or "",
                            file_path=str(file_path),
                            line_number=item.lineno,
                        )
                    )

            classes.append(
                ClassInfo(
                    name=node.name,
                    methods=methods,
                    docstring=ast.get_docstring(node) or "",
                    file_path=str(file_path),
                    line_number=node.lineno,
                )
            )

    return ModuleDoc(
        file_path=str(file_path),
        module_docstring=module_docstring,
        functions=functions,
        classes=classes,
    )


def generate_api_doc_markdown(module_doc: ModuleDoc, project_root: Path) -> str:
    """从模块文档生成 API 文档 Markdown。"""
    relative_path = Path(module_doc.file_path).relative_to(project_root)
    lines: List[str] = []

    lines.append(f"# API: {relative_path.stem}\n")
    lines.append(f"> 源文件: `{relative_path}`\n")

    if module_doc.module_docstring:
        lines.append(f"## 概述\n\n{module_doc.module_docstring}\n")

    if module_doc.functions:
        lines.append("## 函数\n")
        for func in module_doc.functions:
            params_str = ", ".join(func.parameters) if func.parameters else ""
            returns_str = f" → {func.return_type}" if func.return_type else ""
            lines.append(f"### `{func.name}({params_str}){returns_str}`\n")
            if func.docstring:
                lines.append(f"{func.docstring}\n")
            lines.append(f"*定义于第 {func.line_number} 行*\n")

    if module_doc.classes:
        lines.append("## 类\n")
        for cls in module_doc.classes:
            lines.append(f"### `{cls.name}`\n")
            if cls.docstring:
                lines.append(f"{cls.docstring}\n")
            lines.append(f"*定义于第 {cls.line_number} 行*\n")

            if cls.methods:
                lines.append("**方法：**\n")
                for method in cls.methods:
                    params_str = ", ".join(method.parameters) if method.parameters else ""
                    returns_str = f" → {method.return_type}" if method.return_type else ""
                    lines.append(f"- `{method.name}({params_str}){returns_str}`")
                    if method.docstring:
                        first_line = method.docstring.split("\n")[0]
                        lines.append(f"  — {first_line}")
                    else:
                        lines.append("")
                lines.append("")

    return "\n".join(lines)


def scan_project_for_api_docs(
    project_root: Path,
    max_files: int = 50,
) -> List[ModuleDoc]:
    """扫描项目目录，提取所有模块的文档信息。

    Args:
        project_root: 项目根目录
        max_files: 最大扫描文件数（防止大型项目卡死）

    Returns:
        模块文档列表
    """
    modules: List[ModuleDoc] = []
    scanned = 0

    for py_file in project_root.rglob("*.py"):
        if scanned >= max_files:
            break
        rel = py_file.relative_to(project_root)
        if any(
            part.startswith(".") or part in ("venv", "node_modules", "__pycache__")
            for part in rel.parts
        ):
            continue

        module_doc = extract_python_module(py_file)
        if module_doc and (module_doc.functions or module_doc.classes):
            modules.append(module_doc)
            scanned += 1

    return modules


def generate_wiki_api_docs(
    project_root: Path,
    wiki_dir: Optional[Path] = None,
) -> List[Path]:
    """生成 Wiki API 文档文件。

    Args:
        project_root: 项目根目录
        wiki_dir: Wiki api-docs 目录（默认 project_root/wiki/api-docs）

    Returns:
        生成的文件路径列表
    """
    if wiki_dir is None:
        wiki_dir = project_root / "wiki" / "api-docs"

    wiki_dir.mkdir(parents=True, exist_ok=True)

    modules = scan_project_for_api_docs(project_root)
    generated_files: List[Path] = []

    # 生成索引页
    index_lines = ["# API 文档索引\n", "自动生成的 API 文档。\n", "## 模块\n"]
    for mod in modules:
        rel = Path(mod.file_path).relative_to(project_root)
        doc_name = rel.with_suffix(".md").name
        index_lines.append(f"- [{rel.stem}]({doc_name}) — `{rel}`\n")

    index_file = wiki_dir / "index.md"
    index_file.write_text("\n".join(index_lines), encoding="utf-8")
    generated_files.append(index_file)

    # 生成每个模块的文档
    for mod in modules:
        rel = Path(mod.file_path).relative_to(project_root)
        doc_name = rel.with_suffix(".md").name
        doc_content = generate_api_doc_markdown(mod, project_root)
        doc_file = wiki_dir / doc_name
        doc_file.write_text(doc_content, encoding="utf-8")
        generated_files.append(doc_file)

    return generated_files
