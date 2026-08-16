"""M3 权限与安全边界 — ``file_tool`` 路径守卫（M1 起读写非对称）。

M1 工具安全加固后语义（与 claw-code read-vs-write asymmetry 对齐）:

- **WRITE** 路径必须 resolve 后落在 ``policy.workspace_root`` 内
  （拒绝 ``..`` 越界、绝对路径越界、符号链接逃逸）。
- **READ / list_dir** 不再强制边界——工作区外只读保持可用。
- ``policy.workspace_root=None`` → WRITE 也不做路径检查（向后兼容缺省）。

更完整的 WRITE 边界用例见 ``test_file_tool_hardening.py``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.file_tool import ListDirTool, ReadFileTool, WriteFileTool

pytestmark = pytest.mark.unit


def _policy_with_root(root: Path) -> ToolPolicy:
    return ToolPolicy(workspace_root=str(root))


# ============================================================================
# ReadFileTool — M1 起 READ 不强制边界
# ============================================================================


def test_read_file_inside_workspace_root_succeeds(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("hi", encoding="utf-8")
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(f))

    assert result.success is True


def test_read_file_outside_workspace_root_allowed_asymmetry(tmp_path):
    """M1 读写非对称: 绝对路径在 workspace 之外 → READ 仍放行。"""
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(outside))

    assert result.success is True
    assert "secret" in result.content["content"]


def test_read_file_dotdot_traversal_allowed_asymmetry(tmp_path):
    """M1 读写非对称: ``../`` 路径 READ 不再拒绝（写操作才拦）。"""
    sub = tmp_path / "sub"
    sub.mkdir()
    outside_secret = tmp_path.parent / f"escaped_secret_{sub.name}.txt"
    outside_secret.write_text("secret", encoding="utf-8")
    try:
        traversal = str(sub / ".." / ".." / outside_secret.name)
        tool = ReadFileTool(policy=_policy_with_root(tmp_path))

        result = tool.execute(path=traversal)

        assert result.success is True
    finally:
        outside_secret.unlink(missing_ok=True)


def test_read_file_symlink_escape_allowed_asymmetry(tmp_path):
    """M1 读写非对称: 符号链接指向 workspace 外 → READ 放行。

    注: WRITE 侧的同形逃逸仍被拒，见 test_file_tool_hardening.py
    ``test_write_file_symlink_escape_rejected``。
    """
    inside = tmp_path / "link.txt"
    outside = tmp_path.parent / "real.txt"
    outside.write_text("secret", encoding="utf-8")
    inside.symlink_to(outside)
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(inside))

    assert result.success is True


def test_read_file_no_workspace_root_does_not_check_path(tmp_path):
    """缺省 policy（workspace_root=None）→ 不做路径检查（向后兼容）。"""
    f = tmp_path / "anywhere.txt"
    f.write_text("ok", encoding="utf-8")
    tool = ReadFileTool()  # 缺省 ToolPolicy() 无 workspace_root

    result = tool.execute(path=str(f))

    assert result.success is True


# ============================================================================
# WriteFileTool — 路径守卫（M1 起唯一强制边界的文件操作）
# ============================================================================


def test_write_file_outside_workspace_root_rejected(tmp_path):
    target = tmp_path.parent / "new.txt"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="x")

    assert result.success is False
    # 实际不应被创建
    assert not target.exists()


# ============================================================================
# ListDirTool — M1 起 READ 能力不强制边界
# ============================================================================


def test_list_dir_outside_workspace_root_allowed_asymmetry(tmp_path):
    """M1 读写非对称: list_dir 属 READ 能力 → 工作区外放行。"""
    tool = ListDirTool(policy=_policy_with_root(tmp_path))
    result = tool.execute(path=str(tmp_path.parent))
    assert result.success is True


def test_list_dir_inside_workspace_root_succeeds(tmp_path):
    (tmp_path / "f").write_text("x", encoding="utf-8")
    tool = ListDirTool(policy=_policy_with_root(tmp_path))
    result = tool.execute(path=str(tmp_path))
    assert result.success is True
