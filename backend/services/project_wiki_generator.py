"""代码→Wiki 自动生成服务 (M5, 2026-10-12)。

扫描项目代码库，提取符号和依赖关系，调用 LLM 规划文档结构，
逐模块生成 Wiki 页面写入 wiki/ 目录。

架构:
  1. scan_files()       — 遍历 allowed_paths 内源文件
  2. extract_symbols()  — Python AST 提取函数/类/方法
  3. build_dependency_graph() — import/inherit 关系图
  4. plan_documentation()     — LLM 规划文档结构
  5. generate_pages()         — 逐模块生成 Markdown
  6. write_wiki_pages()       — 写入 wiki/ 目录

复用现有设施:
  - allowed_paths 引擎 (backend/office/allowed_paths.py)
  - wiki.files.secure_write_file() 安全写入
  - wiki.wiki_templates 项目类型目录结构
  - OrchestrationService LLM 客户端
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from backend.utils import py_compat

logger = logging.getLogger(__name__)

# 支持的源文件扩展名
PYTHON_EXTENSIONS = {".py"}
ALL_SOURCE_EXTENSIONS = PYTHON_EXTENSIONS | {
    ".ts", ".tsx", ".js", ".jsx",
    ".rs", ".go", ".java", ".cpp", ".c", ".h",
}

# 排除目录
EXCLUDED_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".eggs", ".next", ".nuxt",
}

# Wiki 输出子目录
WIKI_OUTPUT_DIR = "wiki"
WIKI_ARCHITECTURE_DIR = "wiki/architecture"
WIKI_API_DOCS_DIR = "wiki/api-docs"


@dataclass
class SourceFile:
    """扫描到的源文件。"""

    path: str  # 相对路径
    absolute_path: str
    language: str
    size_bytes: int
    content_hash: str  # 用于增量更新


@dataclass
class SymbolInfo:
    """提取的符号信息。"""

    name: str
    kind: str  # "function", "class", "method", "async_function"
    lineno: int
    end_lineno: Optional[int]
    docstring: Optional[str]
    decorators: List[str]
    parent: Optional[str]  # 类名（method 时）
    file_path: str
    # Python 特有
    args: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    bases: List[str] = field(default_factory=list)  # 类继承


@dataclass
class DependencyEdge:
    """依赖图的边。"""

    source: str  # 文件路径
    target: str  # 文件路径或模块名
    kind: str  # "import", "inherit", "call"


@dataclass
class DocumentationPlan:
    """LLM 生成的文档结构规划。"""

    pages: List[Dict[str, Any]]  # [{title, path, type, files, symbols}]
    reasoning: str


@dataclass
class GenerationResult:
    """代码→Wiki 生成结果。"""

    pages_generated: int
    pages_updated: int
    pages_skipped: int
    errors: List[str]
    wiki_paths: List[str]


class ProjectWikiGenerator:
    """项目 Wiki 自动生成器。

    使用方式::

        generator = ProjectWikiGenerator()
        result = await generator.generate(project_id)
        # 或增量更新
        result = await generator.generate(project_id, incremental=True)
    """

    def __init__(self) -> None:
        self._llm_client: Optional[Any] = None
        self._available: Optional[bool] = None

    @property
    def available(self) -> bool:
        """LLM 客户端是否可用。"""
        if self._available is None:
            try:
                from backend.orchestration.llm_factory import (
                    build_llm_client_from_settings,
                )
                self._llm_client = build_llm_client_from_settings()
                self._available = self._llm_client is not None
            except Exception:
                self._available = False
        return self._available

    # ── 步骤 1: 文件扫描 ──────────────────────────────────────────────────────

    def scan_files(
        self,
        project_root: str,
        allowed_paths: Optional[List[str]] = None,
        languages: Optional[Set[str]] = None,
    ) -> List[SourceFile]:
        """扫描项目内的源文件。

        Args:
            project_root: 项目根目录
            allowed_paths: 允许访问的路径规则 (glob patterns)
            languages: 语言过滤 (默认扫描全部支持的源文件)

        Returns:
            SourceFile 列表
        """
        if languages is None:
            languages = {
                "python",
                "typescript",
                "javascript",
                "rust",
                "go",
                "java",
                "cpp",
                "c",
            }

        extensions = PYTHON_EXTENSIONS if languages == {"python"} else ALL_SOURCE_EXTENSIONS
        root = Path(project_root)

        if not root.is_dir():
            logger.warning("项目目录不存在: %s", project_root)
            return []

        # 加载 allowed_paths 引擎
        path_filter = self._build_path_filter(allowed_paths, project_root)

        files: List[SourceFile] = []
        for dirpath, dirnames, filenames in os.walk(root):
            # 排除不需要的目录
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDED_DIRS and not d.startswith(".")
            ]

            for filename in filenames:
                ext = Path(filename).suffix.lower()
                if ext not in extensions:
                    continue

                abs_path = Path(dirpath) / filename
                rel_path = abs_path.relative_to(root)
<<<<<<< HEAD

=======
>>>>>>> origin/main
                # SourceFile.path 是项目相对逻辑标识（供 wiki/依赖分析/前端展示），
                # 统一 POSIX 分隔符，避免 Windows 反斜杠污染序列化结果。
                rel_posix = rel_path.as_posix()

                # 检查 allowed_paths
                if path_filter and not path_filter(rel_posix):
                    continue

                try:
                    content = abs_path.read_bytes()
                    content_hash = hashlib.md5(content).hexdigest()
                    files.append(SourceFile(
                        path=rel_posix,
                        absolute_path=str(abs_path),
                        language=self._detect_language(ext),
                        size_bytes=len(content),
                        content_hash=content_hash,
                    ))
                except Exception as exc:
                    logger.debug("读取文件失败 %s: %s", abs_path, exc)

        logger.info("扫描完成: %d 个源文件", len(files))
        return files

    def _build_path_filter(
        self,
        allowed_paths: Optional[List[str]],
        project_root: str,
    ) -> Optional[Any]:
        """构建路径过滤器。"""
        if not allowed_paths:
            return None

        try:
            from backend.office.allowed_paths import is_allowed

            def filter_fn(path: str) -> bool:
                return is_allowed(path, allowed_paths, project_root)

            return filter_fn
        except ImportError:
            logger.debug("allowed_paths 引擎不可用，扫描全部文件")
            return None

    def _detect_language(self, ext: str) -> str:
        """从扩展名检测语言。"""
        mapping = {
            ".py": "python",
            ".ts": "typescript", ".tsx": "typescript",
            ".js": "javascript", ".jsx": "javascript",
            ".rs": "rust", ".go": "go",
            ".java": "java", ".cpp": "cpp", ".c": "c", ".h": "c",
        }
        return mapping.get(ext, "unknown")

    # ── 步骤 2: 符号提取 (Python AST) ────────────────────────────────────────

    def extract_symbols(self, source_files: List[SourceFile]) -> List[SymbolInfo]:
        """从源文件提取符号信息。

        目前仅支持 Python (AST)。其他语言返回空列表。

        Args:
            source_files: 扫描到的源文件列表

        Returns:
            SymbolInfo 列表
        """
        symbols: List[SymbolInfo] = []

        for sf in source_files:
            if sf.language != "python":
                continue

            try:
                content = Path(sf.absolute_path).read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=sf.path)
                file_symbols = self._extract_python_symbols(tree, sf.path)
                symbols.extend(file_symbols)
            except SyntaxError as exc:
                logger.debug("Python 语法错误 %s: %s", sf.path, exc)
            except Exception as exc:
                logger.debug("符号提取失败 %s: %s", sf.path, exc)

        logger.info("符号提取完成: %d 个符号", len(symbols))
        return symbols

    def _extract_python_symbols(
        self, tree: ast.Module, file_path: str
    ) -> List[SymbolInfo]:
        """从 Python AST 提取符号。"""
        symbols: List[SymbolInfo] = []

        # 收集类内部的方法节点 ID，避免 ast.walk 重复提取
        class_body_func_ids: Set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):  # noqa: UP038
                        class_body_func_ids.add(id(item))

        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):  # noqa: UP038
                # 跳过已在 ClassDef 内处理过的方法
                if id(node) in class_body_func_ids:
                    continue
                kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                symbols.append(SymbolInfo(
                    name=node.name,
                    kind=kind,
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    docstring=ast.get_docstring(node),
                    decorators=[self._format_decorator(d) for d in node.decorator_list],
                    parent=None,
                    file_path=file_path,
                    args=self._extract_args(node.args),
                    return_type=self._format_annotation(node.returns),
                ))

            elif isinstance(node, ast.ClassDef):
                symbols.append(SymbolInfo(
                    name=node.name,
                    kind="class",
                    lineno=node.lineno,
                    end_lineno=getattr(node, "end_lineno", None),
                    docstring=ast.get_docstring(node),
                    decorators=[self._format_decorator(d) for d in node.decorator_list],
                    parent=None,
                    file_path=file_path,
                    bases=[self._format_base(b) for b in node.bases],
                ))

                # 类方法
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):  # noqa: UP038
                        kind = "async_method" if isinstance(item, ast.AsyncFunctionDef) else "method"
                        symbols.append(SymbolInfo(
                            name=item.name,
                            kind=kind,
                            lineno=item.lineno,
                            end_lineno=getattr(item, "end_lineno", None),
                            docstring=ast.get_docstring(item),
                            decorators=[self._format_decorator(d) for d in item.decorator_list],
                            parent=node.name,
                            file_path=file_path,
                            args=self._extract_args(item.args),
                            return_type=self._format_annotation(item.returns),
                        ))

        return symbols

    def _extract_args(self, args: ast.arguments) -> List[str]:
        """提取函数参数名列表。"""
        result: List[str] = []
        for arg in args.args:
            if arg.arg != "self":  # 跳过 self
                result.append(arg.arg)
        return result

    def _format_annotation(self, node: Optional[ast.expr]) -> Optional[str]:
        """格式化类型注解。"""
        if node is None:
            return None
        try:
            return py_compat.ast_unparse(node)
        except Exception:
            return None

    def _format_base(self, node: ast.expr) -> str:
        """格式化类继承基类。"""
        try:
            return py_compat.ast_unparse(node)
        except Exception:
            return "Unknown"

    def _format_decorator(self, node: ast.expr) -> str:
        """格式化装饰器。"""
        try:
            return py_compat.ast_unparse(node)
        except Exception:
            return "unknown"

    # ── 步骤 3: 依赖图 ────────────────────────────────────────────────────────

    def build_dependency_graph(
        self,
        source_files: List[SourceFile],
        symbols: List[SymbolInfo],
    ) -> List[DependencyEdge]:
        """构建依赖关系图。

        Args:
            source_files: 源文件列表
            symbols: 符号列表

        Returns:
            DependencyEdge 列表
        """
        edges: List[DependencyEdge] = []
        file_set = {sf.path for sf in source_files}

        # 只处理 Python 文件的 import
        python_files = [sf for sf in source_files if sf.language == "python"]

        for sf in python_files:
            try:
                content = Path(sf.absolute_path).read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=sf.path)

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            target = self._resolve_import(alias.name, file_set)
                            if target:
                                edges.append(DependencyEdge(
                                    source=sf.path,
                                    target=target,
                                    kind="import",
                                ))

                    elif isinstance(node, ast.ImportFrom):  # noqa: SIM102
                        if node.module and (target := self._resolve_import(node.module, file_set)):
                            edges.append(DependencyEdge(
                                source=sf.path,
                                target=target,
                                kind="import",
                            ))

            except Exception as exc:
                logger.debug("依赖分析失败 %s: %s", sf.path, exc)

        # 类继承关系
        for sym in symbols:
            if sym.kind == "class" and sym.bases:
                for base in sym.bases:
                    # 尝试找到基类定义的文件
                    base_file = self._find_class_definition(base, symbols)
                    if base_file:
                        edges.append(DependencyEdge(
                            source=sym.file_path,
                            target=base_file,
                            kind="inherit",
                        ))

        logger.info("依赖图构建完成: %d 条边", len(edges))
        return edges

    def _resolve_import(self, module_name: str, file_set: Set[str]) -> Optional[str]:
        """将 import 模块名解析为项目内文件路径。"""
        # 尝试直接匹配
        parts = module_name.split(".")

        # 尝试各种可能的路径
        candidates = [
            "/".join(parts) + ".py",
            "/".join(parts[:-1]) + "/__init__.py" if len(parts) > 1 else None,
            parts[0] + "/__init__.py",
        ]

        for candidate in candidates:
            if candidate and candidate in file_set:
                return candidate

        return None

    def _find_class_definition(
        self, class_name: str, symbols: List[SymbolInfo]
    ) -> Optional[str]:
        """查找类定义所在文件。"""
        for sym in symbols:
            if sym.kind == "class" and sym.name == class_name:
                return sym.file_path
        return None

    # ── 步骤 4-6: LLM 规划 + 生成 + 写入 ─────────────────────────────────────

    async def generate(
        self,
        project_id: str,
        incremental: bool = False,
    ) -> GenerationResult:
        """生成项目 Wiki 文档。

        Args:
            project_id: 项目 ID
            incremental: 是否增量更新（仅重新生成变化的文件）

        Returns:
            GenerationResult
        """
        from backend.data.project_repo import ProjectRepository

        project = ProjectRepository().get(project_id)
        if project is None:
            return GenerationResult(
                pages_generated=0,
                pages_updated=0,
                pages_skipped=0,
                errors=["项目不存在"],
                wiki_paths=[],
            )

        project_root = project.path
        if not project_root or not os.path.isdir(project_root):
            return GenerationResult(
                pages_generated=0,
                pages_updated=0,
                pages_skipped=0,
                errors=["项目目录不存在"],
                wiki_paths=[],
            )

        # 1. 扫描文件
        source_files = self.scan_files(
            project_root,
            allowed_paths=project.allowed_paths,
        )
        if not source_files:
            return GenerationResult(
                pages_generated=0,
                pages_updated=0,
                pages_skipped=0,
                errors=["未找到源文件"],
                wiki_paths=[],
            )

        # 2. 提取符号
        symbols = self.extract_symbols(source_files)

        # 3. 构建依赖图
        edges = self.build_dependency_graph(source_files, symbols)

        # 4. LLM 规划文档结构
        if not self.available:
            fallback_pages = self.build_fallback_pages(
                project=project,
                source_files=source_files,
                symbols=symbols,
            )
            fallback_paths = self._write_wiki_pages(project_root, fallback_pages)
            return GenerationResult(
                pages_generated=len(fallback_paths),
                pages_updated=0,
                pages_skipped=0,
                errors=[],
                wiki_paths=fallback_paths,
            )

        try:
            plan = await self._plan_documentation(
                project=project,
                source_files=source_files,
                symbols=symbols,
                edges=edges,
            )
        except Exception as exc:
            logger.error("文档规划失败: %s", exc)
            return GenerationResult(
                pages_generated=0,
                pages_updated=0,
                pages_skipped=0,
                errors=[f"文档规划失败: {exc}"],
                wiki_paths=[],
            )

        # 5. 生成页面
        generated_pages = await self._generate_pages(
            project=project,
            plan=plan,
            source_files=source_files,
            symbols=symbols,
            edges=edges,
        )

        # 6. 写入 Wiki
        wiki_paths = self._write_wiki_pages(project_root, generated_pages)

        return GenerationResult(
            pages_generated=len(wiki_paths),
            pages_updated=0,  # TODO: 增量更新逻辑
            pages_skipped=0,
            errors=[],
            wiki_paths=wiki_paths,
        )

    def build_fallback_pages(
        self,
        project: Any,
        source_files: List[SourceFile],
        symbols: List[SymbolInfo],
    ) -> List[Dict[str, str]]:
        """无 LLM 时生成的确定性骨架页面（2026-10-29）。

        保证 Wiki 生成在未配置 LLM 的环境下仍然可用：目录总览、符号索引、
        构建与测试指南。内容只来自本地扫描，不调用任何模型。
        """
        from collections import Counter

        root = Path(getattr(project, "path", ""))
        name = getattr(project, "name", None) or root.name or "Project"
        counts = Counter(source_file.language for source_file in source_files)
        language_lines = "\n".join(
            f"- {language}: {count} 个文件"
            for language, count in sorted(counts.items())
        )
        try:
            top_dirs = sorted(
                entry.name
                for entry in root.iterdir()
                if entry.is_dir()
                and not entry.name.startswith(".")
                and entry.name not in EXCLUDED_DIRS
            )[:15]
        except OSError:
            top_dirs = []

        overview = (
            "---\ngenerator: sage\n---\n\n"
            "# {name} 项目总览\n\n"
            "> 由 Sage 在未配置 LLM 时生成的骨架文档；配置 LLM 后可重新生成更完整的文档。\n\n"
            "## 源文件统计\n{langs}\n\n"
            "## 顶层目录\n{dirs}\n"
        ).format(
            name=name,
            langs=language_lines or "- 未扫描到源文件",
            dirs="\n".join(f"- `{d}/`" for d in top_dirs) or "- 无",
        )

        if symbols:
            symbol_lines = "\n".join(
                f"- `{symbol.kind}` `{symbol.name}` — `{symbol.file_path}:{symbol.lineno}`"
                for symbol in symbols[:200]
            )
        else:
            symbol_lines = "未提取到 Python 符号（其他语言的符号索引将在后续版本提供）。"
        symbol_index = (
            "---\ngenerator: sage\n---\n\n# 符号索引\n\n" + symbol_lines + "\n"
        )

        try:
            from backend.services.project_profiler import profile_project

            profile = profile_project(str(root))
            build_commands = "\n".join(
                f"- `{command}`" for command in profile.build_commands
            ) or "- 未识别，请补充构建命令"
            test_frameworks = "、".join(profile.test_frameworks) or "未识别"
        except Exception:
            build_commands = "- 未识别，请补充构建命令"
            test_frameworks = "未识别"

        guide = (
            "---\ngenerator: sage\n---\n\n"
            "# 构建与测试\n\n"
            f"## 构建命令\n{build_commands}\n\n"
            f"## 测试框架\n{test_frameworks}\n"
        )

        return [
            {
                "path": "wiki/architecture/overview.md",
                "title": "项目总览",
                "content": overview,
            },
            {
                "path": "wiki/api-docs/symbol-index.md",
                "title": "符号索引",
                "content": symbol_index,
            },
            {
                "path": "wiki/guides/build-and-test.md",
                "title": "构建与测试",
                "content": guide,
            },
        ]

    async def _plan_documentation(
        self,
        project: Any,
        source_files: List[SourceFile],
        symbols: List[SymbolInfo],
        edges: List[DependencyEdge],
    ) -> DocumentationPlan:
        """调用 LLM 规划文档结构。"""
        # 构建摘要信息
        file_summary = [
            {"path": sf.path, "language": sf.language, "size": sf.size_bytes}
            for sf in source_files[:50]  # 限制数量避免 prompt 过长
        ]

        symbol_summary = [
            {
                "name": s.name,
                "kind": s.kind,
                "file": s.file_path,
                "docstring": (s.docstring or "")[:200],
            }
            for s in symbols[:100]  # 限制数量
        ]

        prompt = f"""你是一个技术文档架构师。根据以下项目信息，规划 Wiki 文档结构。

项目名称: {getattr(project, 'name', 'Unknown')}
项目类型: {getattr(project, 'project_type', 'coding')}
项目描述: {getattr(project, 'description', '') or '无描述'}

源文件列表 (前 50 个):
{self._format_json(file_summary)}

符号列表 (前 100 个):
{self._format_json(symbol_summary)}

请输出 JSON 格式的文档结构规划:
{{
  "reasoning": "简要说明你的规划思路",
  "pages": [
    {{
      "title": "页面标题",
      "path": "wiki/architecture/overview.md",
      "type": "overview",
      "description": "此页面要写什么内容",
      "files": ["相关的源文件路径"],
      "symbols": ["相关的符号名"]
    }}
  ]
}}

页面类型: overview (架构概览), module (模块文档), api (API 文档), guide (使用指南)
路径前缀: wiki/architecture/, wiki/api-docs/, wiki/guides/
"""

        from backend.orchestration.llm_factory import build_llm_client_from_settings
        client = build_llm_client_from_settings()

        response = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )

        # 解析 JSON 响应
        import re
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            import json
            data = json.loads(json_match.group())
            return DocumentationPlan(
                pages=data.get("pages", []),
                reasoning=data.get("reasoning", ""),
            )

        return DocumentationPlan(pages=[], reasoning="LLM 响应解析失败")

    async def _generate_pages(
        self,
        project: Any,
        plan: DocumentationPlan,
        source_files: List[SourceFile],
        symbols: List[SymbolInfo],
        edges: List[DependencyEdge],
    ) -> List[Dict[str, str]]:
        """根据规划逐页生成 Markdown 内容。"""
        generated: List[Dict[str, str]] = []

        for page_spec in plan.pages:
            try:
                content = await self._generate_single_page(
                    project=project,
                    page_spec=page_spec,
                    source_files=source_files,
                    symbols=symbols,
                    edges=edges,
                )
                generated.append({
                    "path": page_spec["path"],
                    "title": page_spec["title"],
                    "content": content,
                })
            except Exception as exc:
                logger.error("生成页面失败 %s: %s", page_spec.get("path"), exc)

        return generated

    async def _generate_single_page(
        self,
        project: Any,
        page_spec: Dict[str, Any],
        source_files: List[SourceFile],
        symbols: List[SymbolInfo],
        edges: List[DependencyEdge],
    ) -> str:
        """生成单个页面的 Markdown 内容。"""
        # 收集相关源文件和符号
        related_files = [
            sf for sf in source_files
            if sf.path in page_spec.get("files", [])
        ]
        related_symbols = [
            s for s in symbols
            if s.name in page_spec.get("symbols", [])
            or s.file_path in page_spec.get("files", [])
        ]

        # 构建 prompt
        file_contents: List[str] = []
        for sf in related_files[:10]:  # 限制数量
            try:
                content = Path(sf.absolute_path).read_text(encoding="utf-8", errors="ignore")
                # 截断过长文件
                if len(content) > 3000:
                    content = content[:3000] + "\n... (截断)"
                file_contents.append(f"### {sf.path}\n```python\n{content}\n```")
            except Exception:
                pass

        symbols_info = [
            f"- {s.kind} `{s.name}`: {s.docstring or '无文档字符串'}"
            for s in related_symbols[:30]
        ]

        prompt = f"""生成 Wiki 页面内容。

页面标题: {page_spec['title']}
页面类型: {page_spec.get('type', 'module')}
页面描述: {page_spec.get('description', '')}

项目: {getattr(project, 'name', 'Unknown')}
项目描述: {getattr(project, 'description', '') or '无描述'}

相关源文件:
{chr(10).join(file_contents) if file_contents else '无'}

相关符号:
{chr(10).join(symbols_info) if symbols_info else '无'}

请输出完整的 Markdown 内容。包含:
- 标题 (# 级别)
- 概述段落
- 代码示例 (如果适用)
- API 参考 (如果是 API 文档)
- 相关链接 (使用 [[wikilink]] 格式)

直接输出 Markdown，不要包裹在代码块中。"""

        from backend.orchestration.llm_factory import build_llm_client_from_settings
        client = build_llm_client_from_settings()

        response = await client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )

        # 添加 frontmatter
        frontmatter = f"""---
title: {page_spec['title']}
type: {page_spec.get('type', 'module')}
generated: true
---

"""
        return frontmatter + response.strip()

    def _write_wiki_pages(
        self,
        project_root: str,
        pages: List[Dict[str, str]],
    ) -> List[str]:
        """将生成的页面写入 Wiki 目录。"""
        from backend.wiki.files import secure_write_file

        written: List[str] = []
        root = Path(project_root)

        for page in pages:
            rel_path = page["path"]
            content = page["content"]

            # 确保目录存在
            full_path = root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                secure_write_file(root, root / rel_path, content)
                written.append(rel_path)
                logger.info("写入 Wiki 页面: %s", rel_path)
            except Exception as exc:
                logger.error("写入失败 %s: %s", rel_path, exc)

        return written

    def _format_json(self, data: Any) -> str:
        """格式化 JSON 用于 prompt。"""
        import json
        return json.dumps(data, ensure_ascii=False, indent=2)


__all__ = [
    "DependencyEdge",
    "DocumentationPlan",
    "GenerationResult",
    "ProjectWikiGenerator",
    "SourceFile",
    "SymbolInfo",
]
