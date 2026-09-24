"""project_milestone_repo 单元测试 (项目类型分类系统, 2026-09-24)。

覆盖:
- create: 创建里程碑
- get/list_by_project: 查询
- update: 更新字段（含自动 completed_at 逻辑）
- mark_completed: 标记完成
- delete: 删除
- count_by_status: 按状态统计

使用 conftest.py 的 autouse ``setup_test_db`` fixture。
"""

from __future__ import annotations

import pytest

from backend.data.project_milestone_repo import (
    MILESTONE_STATUS,
    PROJECT_STAGE_ENUM,
    ProjectMilestoneRepository,
)
from backend.data.project_repo import ProjectRepository


@pytest.fixture()
def project(tmp_path):
    """创建测试项目。"""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return ProjectRepository().register(str(project_dir))


@pytest.fixture()
def milestone_repo(setup_test_db):
    """ProjectMilestoneRepository 实例。"""
    return ProjectMilestoneRepository()


class TestMilestoneCreate:
    """create: 创建里程碑。"""

    def test_create_basic(self, milestone_repo, project):
        """创建基本里程碑。"""
        milestone = milestone_repo.create(
            project_id=project.id,
            title="MVP 发布",
        )
        assert milestone.id is not None
        assert milestone.project_id == project.id
        assert milestone.title == "MVP 发布"
        assert milestone.status == "pending"
        assert milestone.completed_at is None
        assert milestone.sort_order == 0

    def test_create_with_all_fields(self, milestone_repo, project):
        """创建带所有字段的名。"""
        milestone = milestone_repo.create(
            project_id=project.id,
            title="Alpha 测试",
            description="核心功能完成",
            stage="testing",
            due_date="2026-12-31",
            sort_order=2,
        )
        assert milestone.description == "核心功能完成"
        assert milestone.stage == "testing"
        assert milestone.due_date == "2026-12-31"
        assert milestone.sort_order == 2


class TestMilestoneGet:
    """get/list_by_project: 查询。"""

    def test_get_existing(self, milestone_repo, project):
        """获取存在的里程碑。"""
        created = milestone_repo.create(project_id=project.id, title="Test")
        fetched = milestone_repo.get(created.id)
        assert fetched is not None
        assert fetched.title == "Test"

    def test_get_nonexistent(self, milestone_repo):
        """获取不存在的里程碑返回 None。"""
        assert milestone_repo.get("nonexistent") is None

    def test_list_empty(self, milestone_repo, project):
        """空项目列出空列表。"""
        assert milestone_repo.list_by_project(project.id) == []

    def test_list_multiple_sorted(self, milestone_repo, project):
        """多个里程碑按 sort_order 升序。"""
        milestone_repo.create(project_id=project.id, title="Third", sort_order=3)
        milestone_repo.create(project_id=project.id, title="First", sort_order=1)
        milestone_repo.create(project_id=project.id, title="Second", sort_order=2)

        result = milestone_repo.list_by_project(project.id)
        assert [m.title for m in result] == ["First", "Second", "Third"]

    def test_list_filter_by_status(self, milestone_repo, project):
        """按状态过滤。"""
        m1 = milestone_repo.create(project_id=project.id, title="Pending")
        m2 = milestone_repo.create(project_id=project.id, title="Done")
        milestone_repo.mark_completed(m2.id)

        pending = milestone_repo.list_by_project(project.id, status="pending")
        assert len(pending) == 1
        assert pending[0].title == "Pending"

        completed = milestone_repo.list_by_project(project.id, status="completed")
        assert len(completed) == 1
        assert completed[0].title == "Done"


class TestMilestoneUpdate:
    """update: 更新字段。"""

    def test_update_title(self, milestone_repo, project):
        """更新标题。"""
        m = milestone_repo.create(project_id=project.id, title="Old")
        milestone_repo.update(m.id, title="New")
        assert milestone_repo.get(m.id).title == "New"

    def test_update_status_to_completed_sets_timestamp(self, milestone_repo, project):
        """状态改为 completed 时自动设置 completed_at。"""
        m = milestone_repo.create(project_id=project.id, title="Test")
        assert m.completed_at is None

        milestone_repo.update(m.id, status="completed")
        updated = milestone_repo.get(m.id)
        assert updated.status == "completed"
        assert updated.completed_at is not None
        assert updated.completed_at > 0

    def test_update_status_from_completed_clears_timestamp(self, milestone_repo, project):
        """从 completed 改为其他状态时清除 completed_at。"""
        m = milestone_repo.create(project_id=project.id, title="Test")
        milestone_repo.mark_completed(m.id)
        assert milestone_repo.get(m.id).completed_at is not None

        milestone_repo.update(m.id, status="in_progress")
        updated = milestone_repo.get(m.id)
        assert updated.status == "in_progress"
        assert updated.completed_at is None

    def test_update_invalid_status_raises(self, milestone_repo, project):
        """无效状态抛 ValueError。"""
        m = milestone_repo.create(project_id=project.id, title="Test")
        with pytest.raises(ValueError, match="Invalid status"):
            milestone_repo.update(m.id, status="invalid_status")

    def test_update_nonexistent(self, milestone_repo):
        """更新不存在的里程碑返回 False。"""
        assert milestone_repo.update("nonexistent", title="X") is False


class TestMilestoneMarkCompleted:
    """mark_completed: 标记完成。"""

    def test_mark_completed(self, milestone_repo, project):
        """标记完成设置 status 和 completed_at。"""
        m = milestone_repo.create(project_id=project.id, title="Test")
        assert milestone_repo.mark_completed(m.id) is True

        updated = milestone_repo.get(m.id)
        assert updated.status == "completed"
        assert updated.completed_at is not None

    def test_mark_completed_nonexistent(self, milestone_repo):
        """标记不存在的里程碑返回 False。"""
        assert milestone_repo.mark_completed("nonexistent") is False


class TestMilestoneDelete:
    """delete: 删除。"""

    def test_delete_existing(self, milestone_repo, project):
        """删除存在的里程碑。"""
        m = milestone_repo.create(project_id=project.id, title="Test")
        assert milestone_repo.delete(m.id) is True
        assert milestone_repo.get(m.id) is None

    def test_delete_nonexistent(self, milestone_repo):
        """删除不存在的里程碑返回 False。"""
        assert milestone_repo.delete("nonexistent") is False

    def test_delete_by_project(self, milestone_repo, project):
        """批量删除项目的所有里程碑。"""
        milestone_repo.create(project_id=project.id, title="1")
        milestone_repo.create(project_id=project.id, title="2")

        deleted = milestone_repo.delete_by_project(project.id)
        assert deleted == 2
        assert milestone_repo.list_by_project(project.id) == []


class TestMilestoneCountByStatus:
    """count_by_status: 按状态统计。"""

    def test_count_empty(self, milestone_repo, project):
        """空项目返回全零。"""
        counts = milestone_repo.count_by_status(project.id)
        assert counts == {s: 0 for s in MILESTONE_STATUS}

    def test_count_mixed(self, milestone_repo, project):
        """混合状态统计。"""
        milestone_repo.create(project_id=project.id, title="P1")
        milestone_repo.create(project_id=project.id, title="P2")
        m3 = milestone_repo.create(project_id=project.id, title="C1")
        milestone_repo.mark_completed(m3.id)
        m4 = milestone_repo.create(project_id=project.id, title="IP1")
        milestone_repo.update(m4.id, status="in_progress")

        counts = milestone_repo.count_by_status(project.id)
        assert counts["pending"] == 2
        assert counts["completed"] == 1
        assert counts["in_progress"] == 1
        assert counts["blocked"] == 0


class TestProjectStageEnum:
    """PROJECT_STAGE_ENUM: 阶段枚举。"""

    def test_coding_stages(self):
        """coding 类型有正确的阶段。"""
        assert "planning" in PROJECT_STAGE_ENUM["coding"]
        assert "deployment" in PROJECT_STAGE_ENUM["coding"]

    def test_research_stages(self):
        """research 类型有正确的阶段。"""
        assert "proposal" in PROJECT_STAGE_ENUM["research"]
        assert "submission" in PROJECT_STAGE_ENUM["research"]

    def test_business_stages(self):
        """business 类型有正确的阶段。"""
        assert "initiation" in PROJECT_STAGE_ENUM["business"]
        assert "closure" in PROJECT_STAGE_ENUM["business"]

    def test_personal_no_stages(self):
        """personal 类型无阶段。"""
        assert PROJECT_STAGE_ENUM["personal"] is None
