"""M1 工具安全加固 — file_tool 硬限额 / 二进制检测 / 写边界测试。

读写非对称设计 (claw-code file_ops.rs):
- WRITE 强制 workspace 边界 (realpath 前缀比对, 拦 ../ 穿越 + symlink 逃逸)
- READ 不做边界检查 (工作区外只读保持可用)
"""

from __future__ import annotations

import os

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.file_tool import (
    BINARY_SNIFF_BYTES,
    MAX_READ_SIZE_BYTES,
    MAX_WRITE_SIZE_BYTES,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)

pytestmark = pytest.mark.unit


def _policy_with_root(root):
    return ToolPolicy(workspace_root=str(root))


# ---------------------------------------------------------------------------
# 命名常量契约
# ---------------------------------------------------------------------------


def test_size_limit_constants_match_contract():
    """硬限额常量: 读 5 MiB / 写 10 MiB / 嗅探 8 KiB。"""
    # Arrange / Act / Assert
    assert MAX_READ_SIZE_BYTES == 5 * 1024 * 1024
    assert MAX_WRITE_SIZE_BYTES == 10 * 1024 * 1024
    assert BINARY_SNIFF_BYTES == 8 * 1024


# ---------------------------------------------------------------------------
# READ 硬限额 + 二进制检测
# ---------------------------------------------------------------------------


def test_read_file_rejects_file_over_5mib_and_suggests_paging(tmp_path):
    """超过 5 MiB 的文件 → 报错并建议 offset/limit。"""
    # Arrange
    big = tmp_path / "big.bin.txt"
    big.write_bytes(b"a" * (MAX_READ_SIZE_BYTES + 1))
    tool = ReadFileTool()

    # Act
    result = tool.execute(path=str(big))

    # Assert
    assert result.success is False
    assert "file_too_large" in result.error
    assert "offset/limit" in result.error


def test_read_file_accepts_file_just_under_5mib(tmp_path):
    """恰好不超 5 MiB 的文件正常读取 (走 M2 截断路径)。"""
    # Arrange
    ok = tmp_path / "ok.txt"
    ok.write_bytes(b"b" * (MAX_READ_SIZE_BYTES - 10))
    tool = ReadFileTool()

    # Act
    result = tool.execute(path=str(ok))

    # Assert
    assert result.success is True


def test_read_file_rejects_binary_file_by_nul_byte(tmp_path):
    """首 8 KiB 含 NUL 字节 → binary_file 错误。"""
    # Arrange
    binary = tmp_path / "data.dat"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary-stuff")
    tool = ReadFileTool()

    # Act
    result = tool.execute(path=str(binary))

    # Assert
    assert result.success is False
    assert "binary_file" in result.error


def test_read_file_allows_text_with_nul_beyond_sniff_window(tmp_path):
    """NUL 出现在 8 KiB 之后不触发二进制判定 (嗅探窗口限制)。"""
    # Arrange
    text_with_late_nul = tmp_path / "late.txt"
    text_with_late_nul.write_bytes(b"t" * (BINARY_SNIFF_BYTES + 100) + b"\x00" + b"tail")
    tool = ReadFileTool()

    # Act
    result = tool.execute(path=str(text_with_late_nul))

    # Assert
    assert result.success is True


# ---------------------------------------------------------------------------
# WRITE 硬限额
# ---------------------------------------------------------------------------


def test_write_file_rejects_content_over_10mib(tmp_path):
    """写入内容超过 10 MiB → content_too_large 错误, 不落盘。"""
    # Arrange
    target = tmp_path / "huge.txt"
    tool = WriteFileTool()

    # Act
    result = tool.execute(path=str(target), content="c" * (MAX_WRITE_SIZE_BYTES + 1))

    # Assert
    assert result.success is False
    assert "content_too_large" in result.error
    assert not target.exists()


# ---------------------------------------------------------------------------
# WRITE: workspace 边界 (realpath 语义)
# ---------------------------------------------------------------------------


def test_write_file_inside_workspace_succeeds(tmp_path):
    """workspace 内的写入正常放行。"""
    # Arrange
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    # Act
    result = tool.execute(path=str(tmp_path / "ok.txt"), content="hello")

    # Assert
    assert result.success is True
    assert (tmp_path / "ok.txt").read_text() == "hello"


def test_write_file_absolute_path_outside_workspace_rejected(tmp_path):
    """绝对路径在 workspace 之外 → 拒绝且不创建文件。"""
    # Arrange
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    target = outside / "leak.txt"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path / "ws"))
    (tmp_path / "ws").mkdir(exist_ok=True)

    # Act
    result = tool.execute(path=str(target), content="x")

    # Assert
    assert result.success is False
    assert "workspace" in result.error
    assert not target.exists()


def test_write_file_dotdot_traversal_rejected(tmp_path):
    """../ 穿越 → realpath 落在 workspace 外 → 拒绝。"""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    tool = WriteFileTool(policy=_policy_with_root(ws))

    # Act
    result = tool.execute(path=str(ws / ".." / "escaped.txt"), content="x")

    # Assert
    assert result.success is False
    assert "workspace" in result.error
    assert not (tmp_path / "escaped.txt").exists()


def test_write_file_symlink_escape_rejected(tmp_path):
    """workspace 内的符号链接指向外部 → realpath 逃逸 → 拒绝
    (claw-code file_ops.rs is_symlink_escape 等价语义)。"""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("orig")
    link = ws / "sneaky_link"
    os.symlink(str(outside), str(link))
    tool = WriteFileTool(policy=_policy_with_root(ws))

    # Act
    result = tool.execute(path=str(link), content="pwned")

    # Assert
    assert result.success is False
    assert "workspace" in result.error
    assert outside.read_text() == "orig"  # 原文件未被改写


def test_write_file_symlink_staying_inside_workspace_allowed(tmp_path):
    """符号链接解析后仍在 workspace 内 → 放行。"""
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir()
    real = ws / "real.txt"
    real.write_text("orig")
    link = ws / "inner_link"
    os.symlink(str(real), str(link))
    tool = WriteFileTool(policy=_policy_with_root(ws))

    # Act
    result = tool.execute(path=str(link), content="updated")

    # Assert
    assert result.success is True
    assert real.read_text() == "updated"


def test_write_file_without_workspace_root_skips_boundary_check(tmp_path, caplog):
    """未绑定 workspace_root → 不做边界检查 (保留当前行为) + debug 日志。"""
    # Arrange
    tool = WriteFileTool()  # 默认 ToolPolicy 无 workspace_root
    target = tmp_path / "anywhere.txt"

    # Act
    import logging

    with caplog.at_level(logging.DEBUG, logger="backend.tools.file_tool"):
        result = tool.execute(path=str(target), content="x")

    # Assert
    assert result.success is True
    assert any("未绑定 workspace_root" in r.message for r in caplog.records)


def test_write_file_prefix_confusion_sibling_dir_rejected(tmp_path):
    """前缀混淆: /foo/bar2 不应被误判为 /foo/bar 之内。"""
    # Arrange
    ws = tmp_path / "bar"
    ws.mkdir()
    sibling = tmp_path / "bar2"
    sibling.mkdir()
    tool = WriteFileTool(policy=_policy_with_root(ws))

    # Act
    result = tool.execute(path=str(sibling / "x.txt"), content="x")

    # Assert
    assert result.success is False
    assert "workspace" in result.error


# ---------------------------------------------------------------------------
# READ / LIST_DIR: 读写非对称 — 边界不强制
# ---------------------------------------------------------------------------


def test_read_file_outside_workspace_is_allowed_read_write_asymmetry(tmp_path):
    """M1 读写非对称: READ 不强制 workspace 边界。"""
    # Arrange
    outside = tmp_path / "outside.txt"
    outside.write_text("readable")
    ws = tmp_path / "ws"
    ws.mkdir()
    tool = ReadFileTool(policy=_policy_with_root(ws))

    # Act
    result = tool.execute(path=str(outside))

    # Assert
    assert result.success is True
    assert "readable" in result.content["content"]


def test_list_dir_outside_workspace_is_allowed_read_write_asymmetry(tmp_path):
    """M1 读写非对称: list_dir 属 READ 能力, 不强制边界。"""
    # Arrange
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    ws = tmp_path / "ws"
    ws.mkdir()
    tool = ListDirTool(policy=_policy_with_root(ws))

    # Act
    result = tool.execute(path=str(outside))

    # Assert
    assert result.success is True
    assert result.content["items"][0]["name"] == "f.txt"
