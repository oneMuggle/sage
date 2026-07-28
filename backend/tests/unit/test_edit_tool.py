"""M2 edit_file 工具单元测试。

精确字符串替换编辑（移植 claw-code file_ops.rs edit_file）：
唯一匹配要求、多匹配错误、replace_all、文件缺失、空白失配、
写限额 / workspace 边界 / 二进制 / BOM 复用 M1 加固设施。
"""

from __future__ import annotations

import pytest

import backend.tools.edit_tool as edit_module
from backend.domain.tool_policy import ToolPolicy
from backend.tools.edit_tool import EditTool

pytestmark = pytest.mark.unit


@pytest.fixture()
def tool():
    return EditTool()


def _write(tmp_path, name: str, text: str) -> str:
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return str(target)


# ---------------------------------------------------------------------------
# 正常替换路径
# ---------------------------------------------------------------------------


def test_edit_replaces_unique_match_and_reports_change_summary(tmp_path, tool):
    """唯一匹配 → 替换成功，content 含 replacements / 行数变化 / 字节数。"""
    # Arrange
    path = _write(tmp_path, "app.py", "def hello():\n    return 'old'\n")

    # Act
    result = tool.execute(file_path=path, old_string="return 'old'", new_string="return 'new'")

    # Assert
    assert result.success is True
    assert result.content["replacements"] == 1
    assert result.content["lines_removed"] == 1
    assert result.content["lines_added"] == 1
    assert result.content["bytes_written"] > 0
    assert "return 'new'" in (tmp_path / "app.py").read_text(encoding="utf-8")


def test_edit_multiline_replacement_counts_logical_lines(tmp_path, tool):
    """多行片段替换时按逻辑行数统计 lines_added / lines_removed。"""
    # Arrange
    path = _write(tmp_path, "m.txt", "a\nb\nc\n")

    # Act
    result = tool.execute(file_path=path, old_string="a\nb", new_string="x\ny\nz")

    # Assert
    assert result.success is True
    assert result.content["lines_removed"] == 2
    assert result.content["lines_added"] == 3
    assert (tmp_path / "m.txt").read_text(encoding="utf-8") == "x\ny\nz\nc\n"


def test_edit_new_string_empty_deletes_fragment(tmp_path, tool):
    """new_string 为空串 → 删除片段，lines_added 记 0。"""
    # Arrange
    path = _write(tmp_path, "d.txt", "keep\nDELETE_ME\nkeep\n")

    # Act
    result = tool.execute(file_path=path, old_string="DELETE_ME\n", new_string="")

    # Assert
    assert result.success is True
    assert result.content["lines_added"] == 0
    assert "DELETE_ME" not in (tmp_path / "d.txt").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 匹配语义错误
# ---------------------------------------------------------------------------


def test_edit_missing_file_reports_clear_error(tmp_path, tool):
    """文件不存在 → 报错并提示创建用 write_file。"""
    # Act
    result = tool.execute(
        file_path=str(tmp_path / "nope.txt"), old_string="a", new_string="b"
    )

    # Assert
    assert result.success is False
    assert "文件不存在" in result.error
    assert "write_file" in result.error


def test_edit_rejects_identical_old_and_new_string(tmp_path, tool):
    """old_string == new_string → 无意义编辑，直接拒绝。"""
    # Arrange
    path = _write(tmp_path, "same.txt", "hello\n")

    # Act
    result = tool.execute(file_path=path, old_string="hello", new_string="hello")

    # Assert
    assert result.success is False
    assert "必须不同" in result.error


def test_edit_rejects_empty_old_string(tmp_path, tool):
    """空 old_string → 拒绝（防止 str.count('') 的全缝隙替换）。"""
    # Arrange
    path = _write(tmp_path, "e.txt", "abc\n")

    # Act
    result = tool.execute(file_path=path, old_string="", new_string="x")

    # Assert
    assert result.success is False
    assert "old_string 不能为空" in result.error


def test_edit_multi_match_without_replace_all_reports_count(tmp_path, tool):
    """>1 处匹配且 replace_all=false → 报错含匹配数与 replace_all 提示。"""
    # Arrange
    path = _write(tmp_path, "multi.txt", "foo\nbar\nfoo\nbaz\nfoo\n")

    # Act
    result = tool.execute(file_path=path, old_string="foo", new_string="qux")

    # Assert
    assert result.success is False
    assert "匹配不唯一（3 处）" in result.error
    assert "replace_all" in result.error
    # 文件未被改动
    assert (tmp_path / "multi.txt").read_text(encoding="utf-8").count("foo") == 3


def test_edit_replace_all_replaces_every_occurrence(tmp_path, tool):
    """replace_all=true → 全部匹配替换，replacements 记总数。"""
    # Arrange
    path = _write(tmp_path, "all.txt", "foo\nbar\nfoo\n")

    # Act
    result = tool.execute(
        file_path=path, old_string="foo", new_string="qux", replace_all=True
    )

    # Assert
    assert result.success is True
    assert result.content["replacements"] == 2
    text = (tmp_path / "all.txt").read_text(encoding="utf-8")
    assert text.count("qux") == 2
    assert "foo" not in text


def test_edit_whitespace_mismatch_is_not_a_match(tmp_path, tool):
    """精确匹配含空白：old_string 多出文件没有的空白即失配，提示锁定差异行。"""
    # Arrange（文件行尾无空格）
    path = _write(tmp_path, "ws.txt", "value = 1\n")

    # Act（old_string 行尾多了 3 个空格 → 子串失配）
    result = tool.execute(file_path=path, old_string="value = 1   ", new_string="value = 2")

    # Assert
    assert result.success is False
    assert "未在文件中找到" in result.error
    assert "疑似空白差异" in result.error
    assert "第 1 行" in result.error


def test_edit_not_found_error_offers_nearest_line_hint(tmp_path, tool):
    """无空白线索时给出 difflib 最近行提示。"""
    # Arrange
    path = _write(tmp_path, "typo.txt", "def calculate_total(items):\n    return sum(items)\n")

    # Act（函数名拼错）
    result = tool.execute(
        file_path=path, old_string="def calculate_totla(items):", new_string="x"
    )

    # Assert
    assert result.success is False
    assert "最接近的行" in result.error
    assert "calculate_total" in result.error


# ---------------------------------------------------------------------------
# M1 加固设施复用
# ---------------------------------------------------------------------------


def test_edit_enforces_write_size_limit(tmp_path, tool, monkeypatch):
    """编辑后内容超过写限额 → content_too_large（复用 file_tool 常量）。"""
    # Arrange: 把限额临时压到 100 字节
    monkeypatch.setattr(edit_module, "MAX_WRITE_SIZE_BYTES", 100)
    path = _write(tmp_path, "big.txt", "a" * 90 + "\n")

    # Act（替换后膨胀到 ~190 字节）
    result = tool.execute(file_path=path, old_string="a" * 90, new_string="b" * 190)

    # Assert
    assert result.success is False
    assert "content_too_large" in result.error
    # 原文件未被改动
    assert (tmp_path / "big.txt").read_text(encoding="utf-8") == "a" * 90 + "\n"


def test_edit_enforces_workspace_boundary(tmp_path, tool):
    """policy.workspace_root 绑定时，越界路径被拒（path_outside_workspace）。"""
    # Arrange
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    sandboxed = EditTool(policy=ToolPolicy(workspace_root=str(tmp_path / "workspace")))
    (tmp_path / "workspace").mkdir()

    # Act
    result = sandboxed.execute(file_path=str(outside), old_string="secret", new_string="leak")

    # Assert
    assert result.success is False
    assert "path_outside_workspace" in result.error
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_edit_allows_path_inside_workspace(tmp_path):
    """workspace 内的文件正常编辑（边界检查不误伤）。"""
    # Arrange
    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = _write(workspace, "inner.txt", "old\n")
    sandboxed = EditTool(policy=ToolPolicy(workspace_root=str(workspace)))

    # Act
    result = sandboxed.execute(file_path=str(path), old_string="old", new_string="new")

    # Assert
    assert result.success is True
    assert (workspace / "inner.txt").read_text(encoding="utf-8") == "new\n"


def test_edit_rejects_binary_file(tmp_path, tool):
    """首 8 KiB 含 NUL 字节 → binary_file 错误（复用 file_tool 嗅探）。"""
    # Arrange
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x89PNG\x00\x00needle\x00")

    # Act
    result = tool.execute(file_path=str(binary), old_string="needle", new_string="x")

    # Assert
    assert result.success is False
    assert "binary_file" in result.error


def test_edit_preserves_utf8_bom(tmp_path, tool):
    """UTF-8 BOM 文件编辑后仍带 BOM（detect_bom_encoding 回写路径）。"""
    # Arrange（utf-8-sig 编码自动写入 BOM）
    bom_file = tmp_path / "bom.txt"
    bom_file.write_bytes("key=value\n".encode("utf-8-sig"))

    # Act
    result = tool.execute(file_path=str(bom_file), old_string="key=value", new_string="key=42")

    # Assert
    assert result.success is True
    raw = bom_file.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"key=42" in raw


def test_edit_rejects_directory_target(tmp_path, tool):
    """目标是目录 → 干净错误。"""
    # Act
    result = tool.execute(file_path=str(tmp_path), old_string="a", new_string="b")

    # Assert
    assert result.success is False
    assert "不是文件" in result.error
