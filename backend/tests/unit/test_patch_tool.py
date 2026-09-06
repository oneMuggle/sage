"""apply_patch 多文件原子编辑单元测试（对标增强 Phase-2 T5）。

重点验证原子性契约：任一补丁校验失败 → 整批不写（校验阶段只读，
不落盘）。全部用 tmp_path 工作区，跨平台无子进程。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.domain.tool_policy import ToolPolicy
from backend.tools.patch_tool import ApplyPatchTool

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("alpha = 1\nbeta = 2\n", encoding="utf-8", newline="")
    (ws / "b.py").write_text("print('b')\n", encoding="utf-8", newline="")
    return ws


def _tool(ws: Path) -> ApplyPatchTool:
    return ApplyPatchTool(policy=ToolPolicy(workspace_root=str(ws)))


def _read(path: Path) -> str:
    with open(str(path), encoding="utf-8", newline="") as handle:
        return handle.read()


def _patch(file_path: str, old: str, new: str, **extra) -> dict:
    data = {"file_path": file_path, "old_string": old, "new_string": new}
    data.update(extra)
    return data


# ---------------------------------------------------------------------------
# 正常流
# ---------------------------------------------------------------------------


def test_multi_file_atomic_success(workspace):
    result = _tool(workspace).execute(
        patches=[
            _patch("a.py", "alpha = 1", "alpha = 10"),
            _patch("b.py", "print('b')", "print('bb')"),
        ]
    )
    assert result.success is True
    assert result.content["count"] == 2
    assert _read(workspace / "a.py") == "alpha = 10\nbeta = 2\n"
    assert _read(workspace / "b.py") == "print('bb')\n"


def test_same_file_patches_apply_sequentially(workspace):
    """同一文件多个补丁链式生效：第二个匹配第一个的产出。"""
    result = _tool(workspace).execute(
        patches=[
            _patch("a.py", "alpha = 1", "alpha = 10"),
            _patch("a.py", "beta = 2", "beta = 20  # alpha is 10"),
        ]
    )
    assert result.success is True
    assert _read(workspace / "a.py") == "alpha = 10\nbeta = 20  # alpha is 10\n"
    assert result.content["files_changed"][0]["replacements"] == 2


def test_replace_all_entry(workspace):
    (workspace / "c.py").write_text("x x x\n", encoding="utf-8", newline="")
    result = _tool(workspace).execute(
        patches=[_patch("c.py", "x", "y", replace_all=True)]
    )
    assert result.success is True
    assert _read(workspace / "c.py") == "y y y\n"


def test_crlf_outside_patch_preserved(workspace):
    (workspace / "crlf.txt").write_bytes(b"line1\r\nline2\r\n")
    result = _tool(workspace).execute(
        patches=[_patch("crlf.txt", "line2", "LINE2")]
    )
    assert result.success is True
    assert (workspace / "crlf.txt").read_bytes() == b"line1\r\nLINE2\r\n"


# ---------------------------------------------------------------------------
# 原子性：任一失败 → 整批不写
# ---------------------------------------------------------------------------


def test_atomic_rollback_on_miss(workspace):
    result = _tool(workspace).execute(
        patches=[
            _patch("a.py", "alpha = 1", "alpha = 10"),
            _patch("b.py", "NOT-EXISTS", "x"),
        ]
    )
    assert result.success is False
    assert "patches[1]" in (result.error or "")
    assert _read(workspace / "a.py") == "alpha = 1\nbeta = 2\n"  # 未被写入


def test_atomic_rollback_on_ambiguous_match(workspace):
    (workspace / "dup.py").write_text("dup dup\n", encoding="utf-8", newline="")
    result = _tool(workspace).execute(
        patches=[_patch("dup.py", "dup", "unique", replace_all=False)]
    )
    assert result.success is False
    assert "匹配不唯一" in (result.error or "")


def test_atomic_rollback_on_missing_file(workspace):
    result = _tool(workspace).execute(
        patches=[_patch("ghost.py", "a", "b")]
    )
    assert result.success is False
    assert "文件不存在" in (result.error or "")
    assert not (workspace / "ghost.py").exists()


def test_atomic_rollback_on_path_outside_workspace(workspace):
    result = _tool(workspace).execute(
        patches=[_patch("../outside.py", "a", "b")]
    )
    assert result.success is False
    assert "path_outside_workspace" in (result.error or "")
    assert not (workspace.parent / "outside.py").exists()


# ---------------------------------------------------------------------------
# 参数形态
# ---------------------------------------------------------------------------


def test_rejects_bad_call_shapes(workspace):
    tool = _tool(workspace)
    assert tool.execute().success is False
    assert tool.execute(patches="not-a-list").success is False
    assert tool.execute(patches=[]).success is False
    assert tool.execute(patches=[{"file_path": "a.py"}], extra=1).success is False
    assert tool.execute(patches=["not-a-dict"]).success is False
    assert tool.execute(patches=[{"file_path": "a.py", "old_string": "x"}]).success is False
    assert tool.execute(
        patches=[_patch("a.py", "x", "y", bogus=True)]
    ).success is False
    assert tool.execute(patches=[_patch("a.py", "same", "same")]).success is False
    # 既有内容未被破坏
    assert _read(workspace / "a.py") == "alpha = 1\nbeta = 2\n"


def test_patch_count_limit(workspace):
    patches = [_patch(f"f{i}.py", "a", "b") for i in range(33)]
    result = _tool(workspace).execute(patches=patches)
    assert result.success is False
    assert "上限" in (result.error or "")


def test_requires_bound_workspace():
    result = ApplyPatchTool(policy=ToolPolicy()).execute(
        patches=[_patch("a.py", "x", "y")]
    )
    assert result.success is False
    assert "path_outside_workspace" in (result.error or "") or "绑定工作区" in (
        result.error or ""
    )
