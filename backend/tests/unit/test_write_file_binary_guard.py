"""PR-4 of office CRUD completion — write_file 二进制扩展名预检测试。

写路径拿不到 NUL 嗅探机会（content 已是 unicode 字符串），只能按目标
扩展名做预检——确保 LLM 不会把 UTF-8 文本流写到 .png/.pdf/.docx/.zip 等
已知二进制格式上。
"""

from __future__ import annotations

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.file_tool import (
    _BINARY_WRITE_BLACKLIST,
    WriteFileTool,
)

pytestmark = pytest.mark.unit


def _policy_with_root(root):
    return ToolPolicy(workspace_root=str(root))


# ---------------------------------------------------------------------------
# 黑名单常量契约
# ---------------------------------------------------------------------------


def test_blacklist_is_frozenset_and_nonempty():
    """黑名单是 frozenset 且非空（防止 LLM 静默通过）。"""
    assert isinstance(_BINARY_WRITE_BLACKLIST, frozenset)
    assert len(_BINARY_WRITE_BLACKLIST) > 0


def test_blacklist_covers_key_binary_formats():
    """黑名单覆盖关键二进制格式（防止维护时漏删）。"""
    required = {".png", ".pdf", ".docx", ".zip", ".exe", ".mp4"}
    assert required.issubset(_BINARY_WRITE_BLACKLIST)


# ---------------------------------------------------------------------------
# 黑名单命中 -> 拒绝
# ---------------------------------------------------------------------------


def test_write_file_rejects_png_extension(tmp_path):
    """扩展名 .png -> binary_extension_blocked 错误。"""
    target = tmp_path / "x.png"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="hello")

    assert result.success is False
    assert "binary_extension_blocked" in result.error
    assert ".png" in result.error
    assert not target.exists()


def test_write_file_rejects_uppercase_pdf_extension(tmp_path):
    """大写扩展名 .PDF 也要被拒（黑名单按小写匹配）。"""
    target = tmp_path / "x.PDF"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="hello")

    assert result.success is False
    assert "binary_extension_blocked" in result.error
    assert ".pdf" in result.error.lower()
    assert not target.exists()


def test_write_file_rejects_docx_extension(tmp_path):
    """扩展名 .docx -> 拒绝。"""
    target = tmp_path / "report.docx"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="x")

    assert result.success is False
    assert "binary_extension_blocked" in result.error
    assert ".docx" in result.error


def test_write_file_rejects_zip_extension(tmp_path):
    """扩展名 .zip -> 拒绝。"""
    target = tmp_path / "archive.zip"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="x")

    assert result.success is False
    assert "binary_extension_blocked" in result.error


# ---------------------------------------------------------------------------
# 白名单放行 / 无扩展名
# ---------------------------------------------------------------------------


def test_write_file_allows_markdown_extension(tmp_path):
    """白名单扩展名 .md -> 正常写入。"""
    target = tmp_path / "x.md"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="# hello")

    assert result.success is True
    assert target.read_text() == "# hello"


def test_write_file_allows_no_extension(tmp_path):
    """无扩展名文件 -> 不在黑名单 -> 正常写入。"""
    target = tmp_path / "Makefile"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="all: build\n")

    assert result.success is True
    assert target.read_text() == "all: build\n"


# ---------------------------------------------------------------------------
# 边界顺序：二进制拒绝不落盘
# ---------------------------------------------------------------------------


def test_write_file_binary_rejection_does_not_create_file(tmp_path):
    """二进制拒绝时不创建文件（早返回语义）。"""
    target = tmp_path / "x.exe"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="MZ...")

    assert result.success is False
    assert "binary_extension_blocked" in result.error
    assert not target.exists()
