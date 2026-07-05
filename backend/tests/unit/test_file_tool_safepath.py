"""M3 权限与安全边界 — ``file_tool`` 路径守卫（激活死代码 ``_is_safe_path``）。

- 文件/目录路径必须 resolve 后落在 ``policy.workspace_root`` 内。
- 拒绝：``..`` 越界、绝对路径越界、符号链接逃逸。
- ``policy.workspace_root=None`` → 不做路径检查（向后兼容缺省）。
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
# ReadFileTool — 路径守卫
# ============================================================================


def test_read_file_inside_workspace_root_succeeds(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("hi", encoding="utf-8")
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(f))

    assert result.success is True


def test_read_file_outside_workspace_root_rejected(tmp_path):
    """绝对路径在 workspace 之外 → success=False。"""
    inside = tmp_path / "inside.txt"
    inside.write_text("ok", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(outside))

    assert result.success is False
    assert "outside" in (result.error or "") or "workspace" in (result.error or "")


def test_read_file_dotdot_traversal_rejected(tmp_path):
    """``../`` 逃逸 → resolve 后落在 workspace 之外 → 拒绝。"""
    sub = tmp_path / "sub"
    sub.mkdir()
    # 把 secret 文件放到 tmp_path 之外（workspace 的父目录）；用 .. 路径试图读取
    outside_secret = tmp_path.parent / f"escaped_secret_{sub.name}.txt"
    outside_secret.write_text("secret", encoding="utf-8")
    try:
        # sub/../../escaped_secret.txt resolve 后是 tmp_path.parent/...
        traversal = str(sub / ".." / ".." / outside_secret.name)
        tool = ReadFileTool(policy=_policy_with_root(tmp_path))

        result = tool.execute(path=traversal)

        assert result.success is False
    finally:
        outside_secret.unlink(missing_ok=True)


def test_read_file_absolute_outside_rejected(tmp_path):
    """/etc/passwd 形式 → 拒绝。"""
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))
    result = tool.execute(path="/etc/passwd")
    assert result.success is False


def test_read_file_symlink_escape_rejected(tmp_path):
    """符号链接指向 workspace 外的文件 → 拒绝。"""
    inside = tmp_path / "link.txt"
    outside = tmp_path.parent / "real.txt"
    outside.write_text("secret", encoding="utf-8")
    inside.symlink_to(outside)  # symlink 在 workspace 内指向外面
    tool = ReadFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(inside))

    assert result.success is False


def test_read_file_no_workspace_root_does_not_check_path(tmp_path):
    """缺省 policy（workspace_root=None）→ 不做路径检查（向后兼容）。"""
    f = tmp_path / "anywhere.txt"
    f.write_text("ok", encoding="utf-8")
    tool = ReadFileTool()  # 缺省 ToolPolicy() 无 workspace_root

    result = tool.execute(path=str(f))

    assert result.success is True


# ============================================================================
# WriteFileTool — 路径守卫
# ============================================================================


def test_write_file_outside_workspace_root_rejected(tmp_path):
    target = tmp_path.parent / "new.txt"
    tool = WriteFileTool(policy=_policy_with_root(tmp_path))

    result = tool.execute(path=str(target), content="x")

    assert result.success is False
    # 实际不应被创建
    assert not target.exists()


# ============================================================================
# ListDirTool — 路径守卫
# ============================================================================


def test_list_dir_outside_workspace_root_rejected(tmp_path):
    tool = ListDirTool(policy=_policy_with_root(tmp_path))
    result = tool.execute(path=str(tmp_path.parent))
    assert result.success is False


def test_list_dir_inside_workspace_root_succeeds(tmp_path):
    (tmp_path / "f").write_text("x", encoding="utf-8")
    tool = ListDirTool(policy=_policy_with_root(tmp_path))
    result = tool.execute(path=str(tmp_path))
    assert result.success is True
