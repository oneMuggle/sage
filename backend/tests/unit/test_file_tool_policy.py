"""M2 显式限制 — 文件工具 byte/条数上限。

- ``ReadFileTool`` 大文件 + ``policy.max_read_bytes`` → 截断到 ≤ 上限，
  content 含 ``truncated: True``。
- ``ReadFileTool`` 小文件 → ``truncated: False``。
- ``ListDirTool`` 大量 entries + ``policy.max_result_items`` → 条数截断，
  content 含 ``truncated: True`` + ``total_items``。
- ``ListDirTool`` 少量 → ``truncated: False``。
"""

from __future__ import annotations

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.file_tool import ListDirTool, ReadFileTool

pytestmark = pytest.mark.unit


# ============================================================================
# ReadFileTool — max_read_bytes
# ============================================================================


def test_read_file_truncated_when_exceeds_max_read_bytes(tmp_path):
    """大文件 + 严格 max_read_bytes → content 字节 ≤ 上限，truncated=True。"""
    f = tmp_path / "big.txt"
    f.write_text("a" * 5000, encoding="utf-8")
    tool = ReadFileTool(policy=ToolPolicy(max_read_bytes=512))

    result = tool.execute(path=str(f))

    assert result.success is True
    # content 是 dict {total_lines, content, path, truncated, original_bytes, max_read_bytes}
    c = result.content
    raw = c["content"].encode("utf-8")
    assert len(raw) <= 512
    assert c["truncated"] is True
    assert c["original_bytes"] == 5000
    assert c["max_read_bytes"] == 512


def test_read_file_not_truncated_when_under_limit(tmp_path):
    """小文件 + 宽松 max_read_bytes → truncated=False。"""
    f = tmp_path / "small.txt"
    f.write_text("hello\nworld\n", encoding="utf-8")
    tool = ReadFileTool(policy=ToolPolicy(max_read_bytes=10_000))

    result = tool.execute(path=str(f))

    assert result.success is True
    assert result.content["truncated"] is False
    assert "original_bytes" in result.content  # 仍记录大小便于审计
    assert result.content["original_bytes"] == len(b"hello\nworld\n")


def test_read_file_default_policy_does_not_truncate_small_file(tmp_path):
    """缺省 policy（max_read_bytes=2MB）不截断正常文件。"""
    f = tmp_path / "x.txt"
    f.write_text("tiny", encoding="utf-8")
    tool = ReadFileTool()  # 缺省

    result = tool.execute(path=str(f))

    assert result.success is True
    assert result.content["truncated"] is False


def test_read_file_offset_paging_still_works_with_truncation(tmp_path):
    """截断后 paging（offset/limit）仍可用。"""
    f = tmp_path / "paged.txt"
    # 写 100 行 "lineN"
    f.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    tool = ReadFileTool(policy=ToolPolicy(max_read_bytes=10_000))

    result = tool.execute(path=str(f), offset=10, limit=5)

    assert result.success is True
    selected = result.content["content"]
    # 应包含 line9 到 line13（offset=10 即第 10 行, 5 行）
    assert "line9" in selected
    assert "line13" in selected


# ============================================================================
# ListDirTool — max_result_items
# ============================================================================


def test_list_dir_truncated_when_too_many_items(tmp_path):
    """大量 entries + max_result_items=3 → items ≤ 3, truncated=True, total_items>3。"""
    for i in range(10):
        (tmp_path / f"file_{i}.txt").write_text("x", encoding="utf-8")
    tool = ListDirTool(policy=ToolPolicy(max_result_items=3))

    result = tool.execute(path=str(tmp_path))

    assert result.success is True
    assert len(result.content["items"]) == 3
    assert result.content["truncated"] is True
    assert result.content["total_items"] == 10


def test_list_dir_not_truncated_when_under_limit(tmp_path):
    """少量 entries → truncated=False。"""
    for i in range(3):
        (tmp_path / f"f_{i}").write_text("x", encoding="utf-8")
    tool = ListDirTool(policy=ToolPolicy(max_result_items=20))

    result = tool.execute(path=str(tmp_path))

    assert result.success is True
    assert len(result.content["items"]) == 3
    assert result.content["truncated"] is False
    assert result.content["total_items"] == 3


def test_list_dir_default_policy_high_limit_does_not_truncate(tmp_path):
    """缺省 policy（max_result_items=200）不截断 100 项。"""
    for i in range(100):
        (tmp_path / f"f_{i}").write_text("x", encoding="utf-8")
    tool = ListDirTool()

    result = tool.execute(path=str(tmp_path))

    assert result.success is True
    assert result.content["truncated"] is False
    assert result.content["total_items"] == 100
