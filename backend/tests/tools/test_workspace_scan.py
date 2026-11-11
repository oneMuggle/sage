"""工作区扫描测试 — execute_code/bash_tool 执行后补记产物。

覆盖：快照、遍历过滤、diff 记录、session 上下文解析，
以及两个工具的桥接集成（真实 execute() 路径）。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.data.artifact_repo import list_artifacts
from backend.tools._workspace_scan import (
    diff_and_record,
    record_workspace_changes,
    resolve_workspace_root,
    snapshot_workspace,
)
from backend.tools.base import ToolPolicy, ToolResult
from backend.tools.context import (
    ToolExecutionContext,
    reset_tool_context,
    set_tool_context,
)

pytestmark = pytest.mark.unit


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _bind_session(session_id: str):
    ctx = ToolExecutionContext(
        session_id=session_id,
        stream_id="stream-test",
        binding_generation=0,
        office_doc_scope=frozenset(),
    )
    return set_tool_context(ctx)


def test_snapshot_workspace(tmp_path: Path) -> None:
    """snapshot_workspace 应返回所有文件的相对路径和 mtime"""
    _write(tmp_path / "a.txt", "a")
    _write(tmp_path / "sub" / "b.txt", "b")

    snap = snapshot_workspace(tmp_path)
    assert "a.txt" in snap
    assert str(Path("sub") / "b.txt") in snap
    assert all(isinstance(v, float) for v in snap.values())


def test_snapshot_skips_hidden_and_ignored(tmp_path: Path) -> None:
    """隐藏文件/目录、依赖目录、编译/系统垃圾文件都不进快照。"""
    _write(tmp_path / "visible.txt")
    _write(tmp_path / "report.html")
    _write(tmp_path / ".hidden.txt")
    _write(tmp_path / ".git" / "config")
    _write(tmp_path / "node_modules" / "pkg" / "index.js")
    _write(tmp_path / "__pycache__" / "mod.cpython-310.pyc")
    _write(tmp_path / "sub" / ".secret" / "x.txt")
    _write(tmp_path / "run.pyc")
    _write(tmp_path / "Thumbs.db")
    _write(tmp_path / "~$locked.docx")

    snap = snapshot_workspace(tmp_path)
    assert "visible.txt" in snap
    assert "report.html" in snap
    assert ".hidden.txt" not in snap
    assert str(Path("sub") / ".secret" / "x.txt") not in snap
    assert not any("node_modules" in rel for rel in snap)
    assert not any("__pycache__" in rel for rel in snap)
    assert not any(rel.endswith((".pyc", ".db", ".docx")) for rel in snap)


def test_diff_and_record_new_files(tmp_path: Path) -> None:
    """diff_and_record 应记录新增文件与修改文件（去重后 2 条）"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = workspace / "existing.txt"
    existing.write_text("old", encoding="utf-8")

    before = snapshot_workspace(workspace)

    _write(workspace / "new.html", "<html>new</html>")
    existing.write_text("new content", encoding="utf-8")
    # 强制 mtime 前进，避免文件系统时间戳粒度导致"修改"漏判
    key = str(Path("existing.txt"))
    bumped = before[key] + 10.0
    os.utime(existing, (bumped, bumped))

    session_id = "sess_scan"
    count = diff_and_record(workspace, before, session_id)

    assert count == 2, f"Expected 2 new/modified files, got {count}"
    artifacts = list_artifacts(session_id)
    assert len(artifacts) == 2
    assert {a.name for a in artifacts} == {"existing.txt", "new.html"}


def test_diff_and_record_unchanged_files_not_recorded(tmp_path: Path) -> None:
    """无变化时 diff 返回 0，不产生 artifact。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write(workspace / "keep.txt")
    before = snapshot_workspace(workspace)

    count = diff_and_record(workspace, before, "sess_unchanged")
    assert count == 0
    assert list_artifacts("sess_unchanged") == []


def test_diff_and_record_requires_session_id(tmp_path: Path) -> None:
    """没有 session_id 时直接跳过，不写库。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    before = snapshot_workspace(workspace)
    _write(workspace / "a.txt")

    assert diff_and_record(workspace, before, "") == 0


def test_resolve_workspace_root_prefers_policy(tmp_path: Path) -> None:
    """显式 policy.workspace_root 优先，且必须真实存在。"""
    assert resolve_workspace_root(ToolPolicy(workspace_root=str(tmp_path))) == tmp_path
    assert resolve_workspace_root(ToolPolicy(workspace_root=str(tmp_path / "missing"))) is None


def test_resolve_workspace_root_without_context_returns_none() -> None:
    """无 policy 且无工具上下文时返回 None（不触发 DB/绑定查询）。"""
    assert resolve_workspace_root(ToolPolicy()) is None


def test_record_workspace_changes_reads_session_from_context(tmp_path: Path) -> None:
    """record_workspace_changes 从 ContextVar 取 session_id 并记录新文件。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write(workspace / "a.txt")
    before = snapshot_workspace(workspace)
    _write(workspace / "b.md", "# b")

    token = _bind_session("sess_ctx")
    try:
        assert record_workspace_changes(workspace, before) == 1
        assert [a.name for a in list_artifacts("sess_ctx")] == ["b.md"]
    finally:
        reset_tool_context(token)


def test_execute_code_bridges_script_outputs(tmp_path: Path, monkeypatch) -> None:
    """ExecuteCodeTool.execute() 应把脚本创建的文件补记为 artifact。"""
    from backend.tools.execute_code_tool import ExecuteCodeTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = ExecuteCodeTool(registry=object(), policy=ToolPolicy(workspace_root=str(workspace)))

    def fake_run(script_path, registry, timeout):  # noqa: ARG001 — 替换真实子进程
        _write(workspace / "script_out.csv", "a,b\n1,2\n")
        return ToolResult(success=True, content={"stdout": "ok"})

    monkeypatch.setattr(tool, "_run", fake_run)

    token = _bind_session("sess_exec")
    try:
        result = tool.execute(code="print('ok')")
    finally:
        reset_tool_context(token)

    assert result.success
    assert [a.name for a in list_artifacts("sess_exec")] == ["script_out.csv"]


@pytest.mark.skipif(os.name == "nt", reason="依赖 POSIX shell 重定向")
def test_bash_tool_bridges_command_outputs(tmp_path: Path) -> None:
    """BashTool.execute() 前台执行后应把命令创建的文件补记为 artifact。"""
    from backend.tools.bash_tool import BashTool

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = BashTool(policy=ToolPolicy(workspace_root=str(workspace)))

    token = _bind_session("sess_bash")
    try:
        result = tool.execute(command="printf 'hello' > made.txt")
    finally:
        reset_tool_context(token)

    assert result.success
    names = {a.name for a in list_artifacts("sess_bash")}
    assert "made.txt" in names
