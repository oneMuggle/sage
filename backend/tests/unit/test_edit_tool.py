"""M2 edit_file 工具单元测试。

精确字符串替换编辑（移植 claw-code file_ops.rs edit_file）：
唯一匹配要求、多匹配错误、replace_all、文件缺失、空白失配、
写限额 / workspace 边界 / 二进制 / BOM 复用 M1 加固设施。
审查修复回归：CRLF 行尾保留（FIX-1）、必需参数哨兵 + 未知参数
拒绝（FIX-2）、读前尺寸预检（FIX-6）。
"""

from __future__ import annotations

import os

import pytest

import backend.tools.edit_tool as edit_module
from backend.domain.tool_policy import ToolPolicy
from backend.tools.edit_tool import EditTool
from backend.tools.file_tool import MAX_WRITE_SIZE_BYTES

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


# ---------------------------------------------------------------------------
# FIX-1: CRLF / LF / 混合行尾保留
# ---------------------------------------------------------------------------


def test_edit_preserves_crlf_endings_outside_edit_region(tmp_path, tool):
    """CRLF 文件编辑：片段被替换，其余各行行尾保持 \r\n（原始字节断言）。"""
    # Arrange
    target = tmp_path / "win.txt"
    target.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")

    # Act
    result = tool.execute(file_path=str(target), old_string="beta", new_string="BETA")

    # Assert
    assert result.success is True
    assert target.read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"


def test_edit_preserves_lf_endings(tmp_path, tool):
    """LF 文件编辑后仍是 LF（不被误引入 \r）。"""
    # Arrange
    target = tmp_path / "unix.txt"
    target.write_bytes(b"a\nb\nc\n")

    # Act
    result = tool.execute(file_path=str(target), old_string="b", new_string="B")

    # Assert
    assert result.success is True
    assert target.read_bytes() == b"a\nB\nc\n"


def test_edit_preserves_mixed_endings_outside_edit_region(tmp_path, tool):
    """混合行尾文件：编辑区之外的 CRLF 与 LF 各行均原样保留。"""
    # Arrange
    target = tmp_path / "mixed.txt"
    target.write_bytes(b"one\r\ntwo\nthree\r\n")

    # Act
    result = tool.execute(file_path=str(target), old_string="two", new_string="TWO")

    # Assert
    assert result.success is True
    assert target.read_bytes() == b"one\r\nTWO\nthree\r\n"


# ---------------------------------------------------------------------------
# FIX-2: 必需参数哨兵（None=未提供 → 报错）+ 未知参数拒绝
# ---------------------------------------------------------------------------


def test_edit_missing_new_string_is_error_not_silent_deletion(tmp_path, tool):
    """漏传 new_string → 报错而非静默删除 old_string（哨兵语义）。"""
    # Arrange
    path = _write(tmp_path, "fragile.txt", "keep\nFRAGILE\n")

    # Act —— 不传 new_string
    result = tool.execute(file_path=path, old_string="FRAGILE\n")

    # Assert
    assert result.success is False
    assert "缺少必需参数 new_string" in result.error
    assert "空字符串" in result.error
    # 文件内容未被删除
    assert (tmp_path / "fragile.txt").read_text(encoding="utf-8") == "keep\nFRAGILE\n"


def test_edit_explicit_empty_new_string_is_allowed_deletion(tmp_path, tool):
    """显式空串 new_string = 有意删除，保持支持（claw/Claude 语义）。"""
    # Arrange
    path = _write(tmp_path, "del.txt", "keep\nGONE\n")

    # Act
    result = tool.execute(file_path=path, old_string="GONE\n", new_string="")

    # Assert
    assert result.success is True
    assert (tmp_path / "del.txt").read_text(encoding="utf-8") == "keep\n"


def test_edit_missing_old_string_is_error(tmp_path, tool):
    """漏传 old_string → 干净错误。"""
    # Arrange
    path = _write(tmp_path, "x.txt", "a\n")

    # Act
    result = tool.execute(file_path=path, new_string="b")

    # Assert
    assert result.success is False
    assert "缺少必需参数 old_string" in result.error


def test_edit_missing_file_path_is_error(tool):
    """漏传 file_path → 干净错误（不再 TypeError 外抛）。"""
    # Act
    result = tool.execute(old_string="a", new_string="b")

    # Assert
    assert result.success is False
    assert "缺少必需参数 file_path" in result.error


def test_edit_rejects_non_string_old_and_new_string(tmp_path, tool):
    """old_string / new_string 非字符串 → 干净错误。"""
    # Arrange
    path = _write(tmp_path, "t.txt", "a\n")

    # Act / Assert
    bad_old = tool.execute(file_path=path, old_string=123, new_string="b")
    assert bad_old.success is False
    assert "old_string 必须是字符串" in bad_old.error

    bad_new = tool.execute(file_path=path, old_string="a", new_string=456)
    assert bad_new.success is False
    assert "new_string 必须是字符串" in bad_new.error


def test_edit_rejects_unknown_kwargs_with_valid_param_list(tmp_path, tool):
    """拼错的参数名 → 干净错误并列出合法参数（不再被 **kwargs 静默吞掉）。"""
    # Arrange
    path = _write(tmp_path, "kw.txt", "a\n")

    # Act —— 模拟 LLM 把 new_string 拼成 new_strng
    result = tool.execute(
        file_path=path, old_string="a", new_string="b", new_strng="typo"
    )

    # Assert
    assert result.success is False
    assert "未知参数" in result.error
    assert "new_strng" in result.error
    assert "合法参数" in result.error
    # 文件未被改动
    assert (tmp_path / "kw.txt").read_text(encoding="utf-8") == "a\n"


# ---------------------------------------------------------------------------
# FIX-6: 读前尺寸预检（st_size 比对写限额，不做全量读）
# ---------------------------------------------------------------------------


def test_edit_rejects_oversized_file_before_reading(tmp_path, tool):
    """超过写限额的文件在读入前按 st_size 拒绝（file_too_large）。"""
    # Arrange: truncate 造稀疏文件，不实际分配磁盘，尺寸 = 限额 + 1
    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"seed")
    os.truncate(huge, MAX_WRITE_SIZE_BYTES + 1)

    # Act
    result = tool.execute(file_path=str(huge), old_string="seed", new_string="x")

    # Assert
    assert result.success is False
    assert "file_too_large" in result.error
    assert str(MAX_WRITE_SIZE_BYTES) in result.error
