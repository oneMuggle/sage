"""API 文档自动生成单元测试 (2026-09-25)

项目类型分类系统 - Phase 9.5.2
"""

from __future__ import annotations

from pathlib import Path

from backend.wiki.api_doc_generator import (
    ClassInfo,
    FunctionSignature,
    ModuleDoc,
    extract_python_module,
    generate_api_doc_markdown,
    generate_wiki_api_docs,
    scan_project_for_api_docs,
)


class TestExtractPythonModule:
    """extract_python_module 测试"""

    def test_extracts_functions_with_docstrings(self, tmp_path: Path) -> None:
        py_file = tmp_path / "utils.py"
        py_file.write_text(
            '"""Utility module."""\n\n'
            "def greet(name: str) -> str:\n"
            '    """Say hello."""\n'
            "    return f'Hello, {name}'\n",
            encoding="utf-8",
        )

        result = extract_python_module(py_file)
        assert result is not None
        assert result.module_docstring == "Utility module."
        assert len(result.functions) == 1
        assert result.functions[0].name == "greet"
        assert "name" in result.functions[0].parameters[0]
        assert result.functions[0].return_type == "str"
        assert result.functions[0].docstring == "Say hello."

    def test_extracts_classes_and_methods(self, tmp_path: Path) -> None:
        py_file = tmp_path / "models.py"
        py_file.write_text(
            '"""Models module."""\n\n'
            "class Calculator:\n"
            '    """A calculator class."""\n\n'
            "    def add(self, a: int, b: int) -> int:\n"
            '        """Add two numbers."""\n'
            "        return a + b\n",
            encoding="utf-8",
        )

        result = extract_python_module(py_file)
        assert result is not None
        assert len(result.classes) == 1
        assert result.classes[0].name == "Calculator"
        assert result.classes[0].docstring == "A calculator class."
        assert len(result.classes[0].methods) == 1
        assert result.classes[0].methods[0].name == "add"
        # self should be excluded
        assert not any("self" in p for p in result.classes[0].methods[0].parameters)

    def test_skips_private_functions(self, tmp_path: Path) -> None:
        py_file = tmp_path / "mix.py"
        py_file.write_text(
            "def public_func() -> None:\n    pass\n\n"
            "def _private_func() -> None:\n    pass\n\n"
            "class PublicClass:\n    pass\n\n"
            "class _PrivateClass:\n    pass\n",
            encoding="utf-8",
        )

        result = extract_python_module(py_file)
        assert result is not None
        assert len(result.functions) == 1
        assert result.functions[0].name == "public_func"
        assert len(result.classes) == 1
        assert result.classes[0].name == "PublicClass"

    def test_returns_none_for_syntax_error(self, tmp_path: Path) -> None:
        py_file = tmp_path / "bad.py"
        py_file.write_text("def broken(\n", encoding="utf-8")

        result = extract_python_module(py_file)
        assert result is None

    def test_handles_empty_module(self, tmp_path: Path) -> None:
        py_file = tmp_path / "empty.py"
        py_file.write_text("# just a comment\n", encoding="utf-8")

        result = extract_python_module(py_file)
        assert result is not None
        assert result.functions == []
        assert result.classes == []


class TestGenerateApiDocMarkdown:
    """generate_api_doc_markdown 测试"""

    def test_generates_function_docs(self, tmp_path: Path) -> None:
        module_doc = ModuleDoc(
            file_path=str(tmp_path / "utils.py"),
            module_docstring="Utility helpers.",
            functions=[
                FunctionSignature(
                    name="format_name",
                    parameters=["first: str", "last: str"],
                    return_type="str",
                    docstring="Format a full name.",
                    file_path=str(tmp_path / "utils.py"),
                    line_number=10,
                )
            ],
            classes=[],
        )

        md = generate_api_doc_markdown(module_doc, tmp_path)
        assert "# API: utils" in md
        assert "`format_name(first: str, last: str) → str`" in md
        assert "Format a full name." in md
        assert "*定义于第 10 行*" in md

    def test_generates_class_docs(self, tmp_path: Path) -> None:
        module_doc = ModuleDoc(
            file_path=str(tmp_path / "models.py"),
            module_docstring="",
            functions=[],
            classes=[
                ClassInfo(
                    name="User",
                    methods=[
                        FunctionSignature(
                            name="get_name",
                            parameters=[],
                            return_type="str",
                            docstring="Return user name.",
                            file_path=str(tmp_path / "models.py"),
                            line_number=15,
                        )
                    ],
                    docstring="User model.",
                    file_path=str(tmp_path / "models.py"),
                    line_number=5,
                )
            ],
        )

        md = generate_api_doc_markdown(module_doc, tmp_path)
        assert "## 类" in md
        assert "`User`" in md
        assert "User model." in md
        assert "`get_name() → str`" in md


class TestScanProjectForApiDocs:
    """scan_project_for_api_docs 测试"""

    def test_scans_python_files(self, tmp_path: Path) -> None:
        # 创建测试文件
        (tmp_path / "module_a.py").write_text(
            "def func_a() -> None:\n    pass\n", encoding="utf-8"
        )
        (tmp_path / "module_b.py").write_text(
            "def func_b() -> None:\n    pass\n", encoding="utf-8"
        )

        modules = scan_project_for_api_docs(tmp_path)
        assert len(modules) == 2

    def test_skips_venv_and_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text(
            "def main_func() -> None:\n    pass\n", encoding="utf-8"
        )
        venv_dir = tmp_path / "venv"
        venv_dir.mkdir()
        (venv_dir / "site.py").write_text(
            "def venv_func() -> None:\n    pass\n", encoding="utf-8"
        )

        modules = scan_project_for_api_docs(tmp_path)
        assert len(modules) == 1
        assert modules[0].file_path.endswith("main.py")

    def test_respects_max_files(self, tmp_path: Path) -> None:
        for i in range(10):
            (tmp_path / f"module_{i}.py").write_text(
                f"def func_{i}() -> None:\n    pass\n", encoding="utf-8"
            )

        modules = scan_project_for_api_docs(tmp_path, max_files=3)
        assert len(modules) == 3


class TestGenerateWikiApiDocs:
    """generate_wiki_api_docs 集成测试"""

    def test_generates_index_and_module_files(self, tmp_path: Path) -> None:
        # 创建项目结构
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "utils.py").write_text(
            "def helper() -> None:\n    pass\n", encoding="utf-8"
        )

        wiki_dir = tmp_path / "wiki" / "api-docs"
        files = generate_wiki_api_docs(tmp_path, wiki_dir)

        assert len(files) >= 2  # index.md + at least one module
        assert wiki_dir.exists()
        assert (wiki_dir / "index.md").exists()
        assert "API 文档索引" in (wiki_dir / "index.md").read_text(encoding="utf-8")

    def test_creates_wiki_dir_if_missing(self, tmp_path: Path) -> None:
        (tmp_path / "code.py").write_text(
            "def some_func() -> None:\n    pass\n", encoding="utf-8"
        )

        custom_wiki = tmp_path / "custom" / "docs"
        files = generate_wiki_api_docs(tmp_path, custom_wiki)

        assert custom_wiki.exists()
        assert len(files) >= 1
