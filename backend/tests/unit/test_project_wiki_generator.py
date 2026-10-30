"""ProjectWikiGenerator 单元测试 (M5, 2026-10-12)。

覆盖:
- SourceFile / SymbolInfo / DependencyEdge / DocumentationPlan / GenerationResult dataclass
- scan_files(): 基本扫描 + 排除目录 + 语言过滤
- extract_symbols(): Python AST 提取函数/类/方法 + 装饰器 + 继承
- build_dependency_graph(): import 解析 + 继承关系
- _detect_language(): 扩展名映射
- _resolve_import(): 模块名→文件路径
- _find_class_definition(): 类名→文件路径
- available 属性: LLM 客户端检测
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.project_wiki_generator import (
    DependencyEdge,
    DocumentationPlan,
    GenerationResult,
    ProjectWikiGenerator,
    SourceFile,
    SymbolInfo,
)

pytestmark = [pytest.mark.unit]


# ── Dataclass tests ───────────────────────────────────────────────────────────


class TestDataclasses:
    def test_source_file_fields(self):
        sf = SourceFile(
            path="src/main.py",
            absolute_path="/proj/src/main.py",
            language="python",
            size_bytes=1024,
            content_hash="abc123",
        )
        assert sf.path == "src/main.py"
        assert sf.language == "python"
        assert sf.size_bytes == 1024

    def test_symbol_info_fields(self):
        s = SymbolInfo(
            name="MyClass",
            kind="class",
            lineno=10,
            end_lineno=50,
            docstring="A test class",
            decorators=["@dataclass"],
            parent=None,
            file_path="src/models.py",
            bases=["BaseModel"],
        )
        assert s.name == "MyClass"
        assert s.kind == "class"
        assert s.bases == ["BaseModel"]

    def test_dependency_edge_fields(self):
        e = DependencyEdge(
            source="src/a.py",
            target="src/b.py",
            kind="import",
        )
        assert e.kind == "import"

    def test_documentation_plan_fields(self):
        p = DocumentationPlan(
            pages=[{"title": "Overview", "path": "wiki/overview.md"}],
            reasoning="Simple project",
        )
        assert len(p.pages) == 1

    def test_generation_result_defaults(self):
        r = GenerationResult(
            pages_generated=3,
            pages_updated=1,
            pages_skipped=2,
            errors=[],
            wiki_paths=["wiki/a.md"],
        )
        assert r.pages_generated == 3


# ── scan_files() ──────────────────────────────────────────────────────────────


class TestScanFiles:
    def test_scan_python_files(self, tmp_path):
        """扫描目录中的 .py 文件。"""
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "utils.py").write_text("def helper(): pass")
        (tmp_path / "readme.txt").write_text("not a python file")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))

        assert len(files) == 2
        assert all(f.language == "python" for f in files)
        assert {f.path for f in files} == {"main.py", "utils.py"}

    def test_excludes_directories(self, tmp_path):
        """排除 node_modules, __pycache__ 等目录。"""
        (tmp_path / "main.py").write_text("pass")
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cached.py").write_text("pass")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))

        assert len(files) == 1
        assert files[0].path == "main.py"

    def test_nested_directories(self, tmp_path):
        """递归扫描子目录。"""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("pass")
        sub = src / "utils"
        sub.mkdir()
        (sub / "helper.py").write_text("pass")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))

        assert len(files) == 2
        paths = {f.path for f in files}
        assert "src/main.py" in paths
        assert "src/utils/helper.py" in paths

    def test_content_hash_computed(self, tmp_path):
        """文件 hash 被正确计算。"""
        (tmp_path / "test.py").write_text("hello world")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))

        assert len(files) == 1
        assert len(files[0].content_hash) == 32  # MD5 hex digest

    def test_nonexistent_directory(self):
        """目录不存在时返回空列表。"""
        gen = ProjectWikiGenerator()
        files = gen.scan_files("/nonexistent/path")
        assert files == []

    def test_language_filter(self, tmp_path):
        """language 过滤。"""
        (tmp_path / "main.py").write_text("pass")
        (tmp_path / "app.js").write_text("console.log('hi')")

        gen = ProjectWikiGenerator()
        # 显式只扫 Python
        files = gen.scan_files(str(tmp_path), languages={"python"})
        assert len(files) == 1
        assert files[0].language == "python"

    def test_scan_all_languages_by_default(self, tmp_path):
        """默认扫描全部支持的源文件（不再只扫 Python）。"""
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "app.ts").write_text("export const x = 1")
        (tmp_path / "main.rs").write_text("fn main() {}")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))

        assert {f.language for f in files} == {"python", "typescript", "rust"}

    def test_build_fallback_pages_without_llm(self, tmp_path):
        """无 LLM 时仍生成确定性骨架页。"""
        from types import SimpleNamespace

        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text("export const x = 1", encoding="utf-8")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))
        pages = gen.build_fallback_pages(
            SimpleNamespace(path=str(tmp_path), name="demo"),
            files,
            [],
        )

        paths = {page["path"] for page in pages}
        assert {
            "wiki/architecture/overview.md",
            "wiki/api-docs/symbol-index.md",
            "wiki/guides/build-and-test.md",
        } <= paths
        assert "typescript" in pages[0]["content"]


# ── extract_symbols() ─────────────────────────────────────────────────────────


class TestExtractSymbols:
    def test_extract_function(self, tmp_path):
        """提取函数定义。"""
        py_file = tmp_path / "funcs.py"
        py_file.write_text("""
def hello(name: str) -> str:
    \"\"\"Say hello.\"\"\"
    return f"Hello, {name}"

async def fetch_data(url: str):
    pass
""")

        sf = SourceFile(
            path="funcs.py",
            absolute_path=str(py_file),
            language="python",
            size_bytes=py_file.stat().st_size,
            content_hash="abc",
        )

        gen = ProjectWikiGenerator()
        symbols = gen.extract_symbols([sf])

        assert len(symbols) == 2
        func = next(s for s in symbols if s.name == "hello")
        assert func.kind == "function"
        assert func.docstring == "Say hello."
        assert func.args == ["name"]
        assert func.return_type == "str"

        async_func = next(s for s in symbols if s.name == "fetch_data")
        assert async_func.kind == "async_function"

    def test_extract_class_and_methods(self, tmp_path):
        """提取类和方法。"""
        py_file = tmp_path / "models.py"
        py_file.write_text("""
class User:
    \"\"\"A user model.\"\"\"

    def __init__(self, name):
        self.name = name

    def greet(self) -> str:
        return f"Hi, I'm {self.name}"
""")

        sf = SourceFile(
            path="models.py",
            absolute_path=str(py_file),
            language="python",
            size_bytes=py_file.stat().st_size,
            content_hash="abc",
        )

        gen = ProjectWikiGenerator()
        symbols = gen.extract_symbols([sf])

        assert len(symbols) == 3  # class + 2 methods
        cls = next(s for s in symbols if s.kind == "class")
        assert cls.name == "User"
        assert cls.docstring == "A user model."

        methods = [s for s in symbols if s.kind == "method"]
        assert len(methods) == 2
        assert all(s.parent == "User" for s in methods)

    def test_extract_decorators(self, tmp_path):
        """提取装饰器。"""
        py_file = tmp_path / "api.py"
        py_file.write_text("""
class Api:
    @property
    def name(self):
        return self._name

    @staticmethod
    def helper():
        pass
""")

        sf = SourceFile(
            path="api.py",
            absolute_path=str(py_file),
            language="python",
            size_bytes=py_file.stat().st_size,
            content_hash="abc",
        )

        gen = ProjectWikiGenerator()
        symbols = gen.extract_symbols([sf])

        prop = next(s for s in symbols if s.name == "name")
        assert "property" in prop.decorators

        static = next(s for s in symbols if s.name == "helper")
        assert "staticmethod" in static.decorators

    def test_skip_non_python(self, tmp_path):
        """非 Python 文件不提取符号。"""
        js_file = tmp_path / "app.js"
        js_file.write_text("function hello() {}")

        sf = SourceFile(
            path="app.js",
            absolute_path=str(js_file),
            language="javascript",
            size_bytes=js_file.stat().st_size,
            content_hash="abc",
        )

        gen = ProjectWikiGenerator()
        symbols = gen.extract_symbols([sf])
        assert symbols == []

    def test_syntax_error_handled(self, tmp_path):
        """语法错误文件被跳过而非抛出。"""
        py_file = tmp_path / "bad.py"
        py_file.write_text("def broken(:\n  pass")

        sf = SourceFile(
            path="bad.py",
            absolute_path=str(py_file),
            language="python",
            size_bytes=py_file.stat().st_size,
            content_hash="abc",
        )

        gen = ProjectWikiGenerator()
        symbols = gen.extract_symbols([sf])
        assert symbols == []


# ── build_dependency_graph() ──────────────────────────────────────────────────


class TestBuildDependencyGraph:
    def test_import_edges(self, tmp_path):
        """import 语句生成依赖边。"""
        (tmp_path / "main.py").write_text("from utils import helper")
        (tmp_path / "utils.py").write_text("def helper(): pass")

        files = [
            SourceFile("main.py", str(tmp_path / "main.py"), "python", 100, "a"),
            SourceFile("utils.py", str(tmp_path / "utils.py"), "python", 100, "b"),
        ]

        gen = ProjectWikiGenerator()
        edges = gen.build_dependency_graph(files, [])

        import_edges = [e for e in edges if e.kind == "import"]
        assert len(import_edges) >= 1
        assert any(e.source == "main.py" and e.target == "utils.py" for e in import_edges)

    def test_inherit_edges(self, tmp_path):
        """类继承生成依赖边。"""
        (tmp_path / "base.py").write_text("""
class BaseModel:
    pass
""")
        (tmp_path / "child.py").write_text("""
from base import BaseModel

class User(BaseModel):
    pass
""")

        files = [
            SourceFile("base.py", str(tmp_path / "base.py"), "python", 100, "a"),
            SourceFile("child.py", str(tmp_path / "child.py"), "python", 100, "b"),
        ]

        gen = ProjectWikiGenerator()
        symbols = gen.extract_symbols(files)
        edges = gen.build_dependency_graph(files, symbols)

        inherit_edges = [e for e in edges if e.kind == "inherit"]
        assert len(inherit_edges) >= 1
        assert any(e.source == "child.py" and e.target == "base.py" for e in inherit_edges)


# ── Helper methods ────────────────────────────────────────────────────────────


class TestHelpers:
    def test_detect_language(self):
        gen = ProjectWikiGenerator()
        assert gen._detect_language(".py") == "python"
        assert gen._detect_language(".ts") == "typescript"
        assert gen._detect_language(".js") == "javascript"
        assert gen._detect_language(".rs") == "rust"
        assert gen._detect_language(".xyz") == "unknown"

    def test_resolve_import_direct(self):
        gen = ProjectWikiGenerator()
        file_set = {"utils.py", "models/user.py"}

        assert gen._resolve_import("utils", file_set) == "utils.py"
        assert gen._resolve_import("models.user", file_set) == "models/user.py"

    def test_resolve_import_init(self):
        gen = ProjectWikiGenerator()
        file_set = {"models/__init__.py"}

        assert gen._resolve_import("models", file_set) == "models/__init__.py"

    def test_resolve_import_not_found(self):
        gen = ProjectWikiGenerator()
        file_set = {"main.py"}

        assert gen._resolve_import("external_lib", file_set) is None

    def test_find_class_definition(self):
        gen = ProjectWikiGenerator()
        symbols = [
            SymbolInfo("BaseModel", "class", 1, 10, None, [], None, "models.py"),
            SymbolInfo("User", "class", 15, 30, None, [], None, "user.py"),
        ]

        assert gen._find_class_definition("User", symbols) == "user.py"
        assert gen._find_class_definition("NonExistent", symbols) is None


# ── available property ────────────────────────────────────────────────────────


class TestAvailable:
    def test_available_with_mock_llm(self):
        gen = ProjectWikiGenerator()
        mock_client = MagicMock()

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=mock_client,
        ):
            assert gen.available is True

    def test_not_available_without_llm(self):
        gen = ProjectWikiGenerator()

        with patch(
            "backend.orchestration.llm_factory.build_llm_client_from_settings",
            return_value=None,
        ):
            assert gen.available is False
