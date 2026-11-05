"""文件引用权限边界测试（P5, 2026-11-05 设计 §9.3/§9.4）。

验证: READ 工具经引用放行只读; WRITE_LOCAL 工具仍被拒绝;
read_file / list_dir 能按虚拟路径读到引用目标。
"""

from __future__ import annotations

import pytest

from backend.data.file_reference_repo import FileReferenceRepository
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.base import BaseTool, ToolSchema
from backend.tools.file_tool import ListDirTool, ReadFileTool

pytestmark = pytest.mark.unit


class _ProbeTool(BaseTool):
    def __init__(self, risk: RiskClass, workspace_root: str) -> None:
        super().__init__(policy=ToolPolicy(workspace_root=workspace_root))
        self.risk = risk

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(name="probe", description="probe")

    def execute(self, **kwargs):
        return None


@pytest.fixture()
def reference_env(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "external"
    target.mkdir()
    (target / "a.md").write_text("hello reference", encoding="utf-8")
    FileReferenceRepository().create(
        "proj-1", "data/cases", str(target), kind="directory"
    )
    monkeypatch.setattr(
        "backend.services.virtual_fs.current_project_id", lambda: "proj-1"
    )
    return workspace, target


def test_read_tool_allows_registered_reference(reference_env):
    workspace, target = reference_env
    tool = _ProbeTool(RiskClass.READ, str(workspace))
    assert tool._enforce_workspace(str(target / "a.md")) is None


def test_write_tool_is_denied_for_reference_target(reference_env):
    workspace, target = reference_env
    tool = _ProbeTool(RiskClass.WRITE_LOCAL, str(workspace))
    result = tool._enforce_workspace(str(target / "new.md"))
    assert result is not None
    assert result.success is False


def test_read_tool_denied_outside_reference_target(reference_env, tmp_path):
    workspace, _ = reference_env
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    tool = _ProbeTool(RiskClass.READ, str(workspace))
    result = tool._enforce_workspace(str(unrelated / "x.md"))
    assert result is not None
    assert result.success is False


def test_translate_virtual_path_returns_target(reference_env):
    workspace, target = reference_env
    tool = _ProbeTool(RiskClass.READ, str(workspace))
    translated, via_reference = tool._translate_virtual_path("data/cases/a.md")
    assert via_reference is True
    assert translated == str(target / "a.md")


def test_read_file_reads_through_reference(reference_env):
    workspace, _ = reference_env
    tool = ReadFileTool(
        policy=ToolPolicy(workspace_root=str(workspace)), enforce_workspace=True
    )
    result = tool.execute(path="data/cases/a.md")
    assert result.success is True
    assert "hello reference" in result.content["content"]


def test_list_dir_lists_through_reference(reference_env):
    workspace, _ = reference_env
    tool = ListDirTool(
        policy=ToolPolicy(workspace_root=str(workspace)), enforce_workspace=True
    )
    result = tool.execute(path="data/cases")
    assert result.success is True
    assert [item["name"] for item in result.content["items"]] == ["a.md"]
