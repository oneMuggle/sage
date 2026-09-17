"""allowed_paths 集成测试。

覆盖：

- project_routes: 注册项目 + allowed_paths、PUT 更新 allowed_paths
- file_tool: enforce_workspace + allowed_paths 放行/拒绝
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from backend.data.project_repo import ProjectRepository
from backend.tools.context import ToolExecutionContext, set_tool_context, reset_tool_context


@pytest.fixture
def repo(tmp_path: Path):
    """每个测试用临时数据库 + repo 实例。"""
    from backend.data.database import Database
    import backend.data.database as db_module

    test_db = Database(str(tmp_path / "test.db"))
    test_db.init_db()
    original_db = db_module._db
    db_module._db = test_db
    try:
        yield ProjectRepository()
    finally:
        db_module._db = original_db


class TestProjectRegisterAllowedPaths:
    """项目注册接口接受 allowed_paths 字段。"""

    def test_register_with_allowed_paths(self, repo: ProjectRepository, tmp_path: Path):
        """注册时携带 allowed_paths，存储到数据库。"""
        ws = tmp_path / "workspace"
        ws.mkdir()

        project = repo.register(
            str(ws),
            allowed_paths=["~/Documents/**", "/tmp/*"],
        )
        assert project.allowed_paths == ["~/Documents/**", "/tmp/*"]

        from backend.data.database import get_database
        conn = get_database().get_connection()
        row = conn.execute(
            "SELECT allowed_paths FROM projects WHERE id = ?", (project.id,)
        ).fetchone()
        stored = json.loads(row["allowed_paths"])
        assert stored == ["~/Documents/**", "/tmp/*"]

    def test_register_without_allowed_paths_defaults_to_empty(
        self, repo: ProjectRepository, tmp_path: Path
    ):
        """未指定 allowed_paths 时默认为空列表。"""
        ws = tmp_path / "workspace"
        ws.mkdir()

        project = repo.register(str(ws))
        assert project.allowed_paths == []


class TestUpdateAllowedPaths:
    """PUT /projects/{id}/allowed-paths 更新路径规则列表。"""

    def test_update_allowed_paths(self, repo: ProjectRepository, tmp_path: Path):
        """更新 allowed_paths 字段。"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        project = repo.register(str(ws))

        updated = repo.update_allowed_paths(project.id, ["~/Desktop/**", "/var/log/*"])
        assert updated is True

        reloaded = repo.get(project.id)
        assert reloaded is not None
        assert reloaded.allowed_paths == ["~/Desktop/**", "/var/log/*"]

    def test_update_allowed_paths_project_not_found(
        self, repo: ProjectRepository
    ):
        """不存在的项目 ID 返回 False。"""
        updated = repo.update_allowed_paths("nonexistent-id", ["~/foo/**"])
        assert updated is False

    def test_update_allowed_paths_to_empty_clears(self, repo: ProjectRepository, tmp_path: Path):
        """允许设置为空列表（清除所有规则）。"""
        ws = tmp_path / "workspace"
        ws.mkdir()
        project = repo.register(str(ws), allowed_paths=["~/Desktop/**"])

        updated = repo.update_allowed_paths(project.id, [])
        assert updated is True

        reloaded = repo.get(project.id)
        assert reloaded is not None
        assert reloaded.allowed_paths == []


class TestFileToolAllowedPathsIntegration:
    """file_tool.py 集成 allowed_paths 检查。"""

    def setup_method(self):
        """每个测试前初始化临时数据库。"""
        self._tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp_db.close()

        from backend.data.database import Database
        import backend.data.database as db_module

        test_db = Database(self._tmp_db.name)
        test_db.init_db()
        self._original_db = db_module._db
        db_module._db = test_db

    def teardown_method(self):
        """清理：恢复原始数据库 + 删除临时文件。"""
        import backend.data.database as db_module
        db_module._db = self._original_db
        if os.path.exists(self._tmp_db.name):
            os.unlink(self._tmp_db.name)

    def test_read_file_allowed_via_allowed_paths(self, tmp_path: Path):
        """路径不在 workspace 内但在 allowed_paths → 放行。"""
        from backend.domain.tool_policy import ToolPolicy
        from backend.office.session_workspace import bind_session_workspace
        from backend.data.session_repo import SessionRepository
        from backend.data.database import get_database
        from backend.tools.file_tool import ReadFileTool

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        external_file = allowed_dir / "data.txt"
        external_file.write_text("external content")

        project = ProjectRepository().register(
            str(workspace), allowed_paths=[f"{allowed_dir}/**"]
        )
        session = SessionRepository().create(title="test")
        bind_session_workspace(
            get_database().get_connection(), session.id, project.path
        )

        ctx = ToolExecutionContext(
            session_id=session.id,
            stream_id="test-stream",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
        token = set_tool_context(ctx)

        try:
            tool = ReadFileTool(
                policy=ToolPolicy(workspace_root=str(workspace)),
                enforce_workspace=True,
            )
            result = tool.execute(path=str(external_file))
            assert result.success is True
            assert "external content" in result.content["content"]
        finally:
            reset_tool_context(token)

    def test_read_file_rejected_when_no_match(self, tmp_path: Path):
        """路径不在 workspace 也不在 allowed_paths → 拒绝。"""
        from backend.domain.tool_policy import ToolPolicy
        from backend.office.session_workspace import bind_session_workspace
        from backend.data.session_repo import SessionRepository
        from backend.data.database import get_database
        from backend.tools.file_tool import ReadFileTool

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        other_file = other_dir / "secret.txt"
        other_file.write_text("secret")

        project = ProjectRepository().register(
            str(workspace),
            allowed_paths=["~/Documents/**"],
        )
        session = SessionRepository().create(title="test")
        bind_session_workspace(
            get_database().get_connection(), session.id, project.path
        )

        ctx = ToolExecutionContext(
            session_id=session.id,
            stream_id="test-stream",
            binding_generation=1,
            office_doc_scope=frozenset(),
        )
        token = set_tool_context(ctx)

        try:
            tool = ReadFileTool(
                policy=ToolPolicy(workspace_root=str(workspace)),
                enforce_workspace=True,
            )
            result = tool.execute(path=str(other_file))
            assert result.success is False
            assert "path_outside_workspace" in result.error
        finally:
            reset_tool_context(token)

    def test_read_file_enforce_false_skips_check(self, tmp_path: Path):
        """enforce_workspace=False 时不做 allowed_paths 检查。"""
        from backend.domain.tool_policy import ToolPolicy
        from backend.tools.file_tool import ReadFileTool

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        other_file = tmp_path / "other.txt"
        other_file.write_text("data")

        tool = ReadFileTool(
            policy=ToolPolicy(workspace_root=str(workspace)),
            enforce_workspace=False,
        )
        result = tool.execute(path=str(other_file))
        assert result.success is True
