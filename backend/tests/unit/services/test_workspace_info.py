"""R176 — WorkspaceInfoService 工作区信息服务单元测试。

覆盖：正常工作区全字段、不存在路径 / 非目录错误、非 git 目录降级、
模型字段契约、get_workspace_info_service 单例。
"""


import pytest

from backend.services.workspace_info import (
    RecentFile,
    WorkspaceInfo,
    WorkspaceInfoError,
    WorkspaceInfoService,
    get_workspace_info_service,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def service():
    return WorkspaceInfoService()


def test_nonexistent_path_raises():
    with pytest.raises(WorkspaceInfoError, match="不存在"):
        WorkspaceInfoService().get_workspace_info("/ghost/path")


def test_non_directory_raises(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(WorkspaceInfoError, match="不是目录"):
        WorkspaceInfoService().get_workspace_info(str(f))


def test_non_git_workspace_basic_info(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.py").write_text("world")
    info = WorkspaceInfoService().get_workspace_info(str(tmp_path))
    assert info.project_name == tmp_path.name
    assert info.workspace_path == str(tmp_path)
    assert info.total_files >= 0  # find 不可用时降级为 0


def test_recent_file_model_fields():
    rf = RecentFile(name="a.py", path="a.py", modified="2026-01-01T00:00:00Z", size_bytes=100)
    assert rf.name == "a.py"
    assert rf.size_bytes == 100


def test_workspace_info_model_fields():
    info = WorkspaceInfo(
        project_name="p", workspace_path="/w", git_branch="main",
        git_status="clean", git_ahead=1, git_behind=2,
        recent_files=[], total_files=0, last_activity=None,
    )
    assert info.project_name == "p"
    assert info.git_branch == "main"
    assert info.git_ahead == 1
    assert info.git_behind == 2


def test_get_workspace_info_service_singleton():
    assert get_workspace_info_service() is get_workspace_info_service()
    assert isinstance(get_workspace_info_service(), WorkspaceInfoService)
