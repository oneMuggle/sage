"""file_summary 工具单元测试。

覆盖:
- Schema 完整性
- Python ast 提取（classes/functions/imports/methods）
- Python 语法错误优雅降级
- JS/TS 正则提取（class/function/arrow const）
- 不支持语言的 fallback（文件头 + 行数）
- 错误路径（二进制/超大文件/不存在/未知参数/空 path）
- language hint 覆盖
- ToolPolicy 注入
"""

from __future__ import annotations

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.file_summary_tool import FileSummaryTool

pytestmark = pytest.mark.unit


# ---- Schema ----


def test_file_summary_schema_has_required_fields():
    """schema 包含 name / parameters / 必需 path。"""
    tool = FileSummaryTool()
    assert tool.schema.name == "file_summary"
    assert "path" in tool.schema.parameters["properties"]
    assert tool.schema.parameters["required"] == ["path"]
    assert tool.risk.value == "read"


# ---- Python ----


def test_python_extracts_classes_functions_imports(tmp_path):
    """Python 文件正确提取 classes / functions / imports / methods。"""
    # Arrange
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "class Foo:\n"
        "    def __init__(self):\n"
        "        pass\n"
        "    def bar(self, x):\n"
        "        return x\n"
        "\n"
        "def baz(a, b):\n"
        "    return a + b\n"
    )
    target = tmp_path / "sample.py"
    target.write_text(code, encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is True
    content = result.content
    assert content["language"] == "python"
    assert content["total_lines"] == 11
    assert [c["name"] for c in content["classes"]] == ["Foo"]
    assert content["classes"][0]["methods"] == ["__init__", "bar"]
    assert [f["name"] for f in content["functions"]] == ["baz"]
    assert content["functions"][0]["params"] == ["a", "b"]
    assert "os" in content["imports"]
    assert any("pathlib" in i for i in content["imports"])


def test_python_syntax_error_returns_error_field_not_exception(tmp_path):
    """Python 语法错误 → 解析返回 error 字段（不抛异常，整体 success=True）。"""
    # Arrange
    target = tmp_path / "broken.py"
    target.write_text("def broken(:\n  pass\n", encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is True  # 整体成功
    assert "error" in result.content
    assert "语法错误" in result.content["error"]
    assert result.content["classes"] == []
    assert result.content["functions"] == []


def test_python_async_function_extracted(tmp_path):
    """async def 也被提取到 functions 中。"""
    # Arrange
    target = tmp_path / "async.py"
    target.write_text("async def fetch(url):\n  pass\n", encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is True
    assert [f["name"] for f in result.content["functions"]] == ["fetch"]
    assert result.content["functions"][0]["params"] == ["url"]


# ---- JavaScript / TypeScript ----


def test_javascript_extracts_exports(tmp_path):
    """JS/TS 文件正则提取 export class / function / const 箭头。"""
    # Arrange
    code = (
        "export class App {\n"
        "  render() { return null; }\n"
        "}\n"
        "\n"
        "export function main() { }\n"
        "\n"
        "export const handler = () => {};\n"
    )
    target = tmp_path / "app.ts"
    target.write_text(code, encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is True
    content = result.content
    assert content["language"] == "typescript"
    assert [c["name"] for c in content["classes"]] == ["App"]
    names = sorted([f["name"] for f in content["functions"]])
    assert names == ["handler", "main"]


def test_javascript_default_export_class(tmp_path):
    """default export class 也能识别。"""
    # Arrange
    target = tmp_path / "widget.jsx"
    target.write_text("export default class Widget {}\n", encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is True
    assert [c["name"] for c in result.content["classes"]] == ["Widget"]


# ---- Fallback ----


def test_unknown_language_returns_head_and_line_count(tmp_path):
    """不支持的语言退化为文件头 30 行 + 行数统计。"""
    # Arrange
    code = "\n".join(f"line {i}" for i in range(50))
    target = tmp_path / "unknown.rust"
    target.write_text(code, encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is True
    content = result.content
    assert content["language"] == "unknown"
    assert content["total_lines"] == 50
    assert "head" in content
    # 30 行 = 29 个换行符
    assert content["head"].count("\n") == 29


# ---- language hint 覆盖 ----


def test_language_hint_overrides_extension(tmp_path):
    """显式 language 参数覆盖后缀检测。"""
    # Arrange: .txt 后缀，但声明为 python
    target = tmp_path / "code.txt"
    target.write_text("def f(): pass\n", encoding="utf-8")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target), language="python")

    # Assert
    assert result.content["language"] == "python"
    assert [f["name"] for f in result.content["functions"]] == ["f"]


# ---- 错误路径 ----


def test_binary_file_rejected(tmp_path):
    """二进制文件 → success=False 干净错误。"""
    # Arrange
    target = tmp_path / "blob.bin"
    target.write_bytes(b"\x00binary\xff")
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is False
    assert "binary_file" in result.error


def test_file_too_large_rejected(tmp_path):
    """超过 5 MiB → success=False（不抛异常）。"""
    # Arrange
    target = tmp_path / "huge.py"
    target.write_bytes(b"x" * (6 * 1024 * 1024))
    tool = FileSummaryTool()

    # Act
    result = tool.execute(path=str(target))

    # Assert
    assert result.success is False
    assert "file_too_large" in result.error


def test_nonexistent_path_returns_error(tmp_path):
    """路径不存在 → success=False。"""
    result = FileSummaryTool().execute(path=str(tmp_path / "missing.py"))
    assert result.success is False
    assert "不存在" in result.error


def test_unknown_kwargs_rejected(tmp_path):
    """未知参数 → 干净错误（FIX-2 模式）。"""
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    # 故意拼错 language
    result = FileSummaryTool().execute(path=str(target), langauge="python")
    assert result.success is False
    assert "未知参数" in result.error
    assert "langauge" in result.error


def test_empty_path_rejected():
    """path 为空字符串 → success=False。"""
    result = FileSummaryTool().execute(path="")
    assert result.success is False
    assert "path 不能为空" in result.error


def test_policy_injection_works(tmp_path):
    """ToolPolicy 通过构造器注入（与现有工具一致）。"""
    tool = FileSummaryTool(policy=ToolPolicy(workspace_root=str(tmp_path)))
    assert tool._policy.workspace_root == str(tmp_path)
