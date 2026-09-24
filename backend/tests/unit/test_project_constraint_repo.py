"""project_constraint_repo 单元测试 (项目类型分类系统, 2026-09-24)。

覆盖:
- create: 创建约束
- get: 按 ID 获取
- list_by_project: 按项目列出
- update: 更新字段
- delete: 删除
- import_template: 从模板导入
- resolve_active: 解析激活的约束（按 trigger_pattern 匹配）

使用 conftest.py 的 autouse ``setup_test_db`` fixture。
"""

from __future__ import annotations

import pytest

from backend.data.project_constraint_repo import (
    CONSTRAINT_TEMPLATES,
    ProjectConstraintRepository,
)
from backend.data.project_repo import ProjectRepository


@pytest.fixture()
def project(tmp_path):
    """创建测试项目。"""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return ProjectRepository().register(str(project_dir))


@pytest.fixture()
def constraint_repo(setup_test_db):
    """ProjectConstraintRepository 实例。"""
    return ProjectConstraintRepository()


class TestConstraintCreate:
    """create: 创建约束。"""

    def test_create_basic(self, constraint_repo, project):
        """创建基本约束。"""
        constraint = constraint_repo.create(
            project_id=project.id,
            category="coding_style",
            content="使用双引号字符串",
        )
        assert constraint.id is not None
        assert constraint.project_id == project.id
        assert constraint.category == "coding_style"
        assert constraint.content == "使用双引号字符串"
        assert constraint.priority == 5  # 默认值
        assert constraint.enabled is True
        assert constraint.trigger_pattern is None

    def test_create_with_all_fields(self, constraint_repo, project):
        """创建带所有字段的约束。"""
        constraint = constraint_repo.create(
            project_id=project.id,
            category="security",
            content="禁止硬编码密钥",
            trigger_pattern="*.py",
            priority=9,
        )
        assert constraint.category == "security"
        assert constraint.trigger_pattern == "*.py"
        assert constraint.priority == 9


class TestConstraintGet:
    """get: 按 ID 获取。"""

    def test_get_existing(self, constraint_repo, project):
        """获取存在的约束。"""
        created = constraint_repo.create(
            project_id=project.id, category="test", content="test"
        )
        fetched = constraint_repo.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.content == created.content

    def test_get_nonexistent(self, constraint_repo):
        """获取不存在的约束返回 None。"""
        assert constraint_repo.get("nonexistent-id") is None


class TestConstraintList:
    """list_by_project: 按项目列出。"""

    def test_list_empty(self, constraint_repo, project):
        """空项目列出空列表。"""
        result = constraint_repo.list_by_project(project.id)
        assert result == []

    def test_list_multiple(self, constraint_repo, project):
        """列出多个约束，按优先级降序。"""
        constraint_repo.create(
            project_id=project.id, category="a", content="low", priority=3
        )
        constraint_repo.create(
            project_id=project.id, category="b", content="high", priority=8
        )
        constraint_repo.create(
            project_id=project.id, category="c", content="mid", priority=5
        )

        result = constraint_repo.list_by_project(project.id)
        assert len(result) == 3
        # 按优先级降序
        assert result[0].content == "high"
        assert result[1].content == "mid"
        assert result[2].content == "low"

    def test_list_enabled_only(self, constraint_repo, project):
        """只列出启用的约束。"""
        c1 = constraint_repo.create(
            project_id=project.id, category="a", content="enabled"
        )
        c2 = constraint_repo.create(
            project_id=project.id, category="b", content="disabled"
        )
        constraint_repo.update(c2.id, enabled=False)

        result = constraint_repo.list_by_project(project.id, enabled_only=True)
        assert len(result) == 1
        assert result[0].id == c1.id


class TestConstraintUpdate:
    """update: 更新字段。"""

    def test_update_single_field(self, constraint_repo, project):
        """更新单个字段。"""
        constraint = constraint_repo.create(
            project_id=project.id, category="test", content="original"
        )
        constraint_repo.update(constraint.id, content="updated")

        updated = constraint_repo.get(constraint.id)
        assert updated.content == "updated"
        assert updated.category == "test"  # 未变

    def test_update_multiple_fields(self, constraint_repo, project):
        """更新多个字段。"""
        constraint = constraint_repo.create(
            project_id=project.id, category="test", content="original", priority=5
        )
        constraint_repo.update(
            constraint.id, category="new_cat", content="new_content", priority=9
        )

        updated = constraint_repo.get(constraint.id)
        assert updated.category == "new_cat"
        assert updated.content == "new_content"
        assert updated.priority == 9

    def test_update_nonexistent(self, constraint_repo):
        """更新不存在的约束返回 False。"""
        result = constraint_repo.update("nonexistent", content="x")
        assert result is False

    def test_update_toggle_enabled(self, constraint_repo, project):
        """切换 enabled 状态。"""
        constraint = constraint_repo.create(
            project_id=project.id, category="test", content="test"
        )
        assert constraint.enabled is True

        constraint_repo.update(constraint.id, enabled=False)
        updated = constraint_repo.get(constraint.id)
        assert updated.enabled is False


class TestConstraintDelete:
    """delete: 删除。"""

    def test_delete_existing(self, constraint_repo, project):
        """删除存在的约束。"""
        constraint = constraint_repo.create(
            project_id=project.id, category="test", content="test"
        )
        assert constraint_repo.delete(constraint.id) is True
        assert constraint_repo.get(constraint.id) is None

    def test_delete_nonexistent(self, constraint_repo):
        """删除不存在的约束返回 False。"""
        assert constraint_repo.delete("nonexistent") is False

    def test_delete_by_project(self, constraint_repo, project):
        """批量删除项目的所有约束。"""
        constraint_repo.create(project_id=project.id, category="a", content="1")
        constraint_repo.create(project_id=project.id, category="b", content="2")
        constraint_repo.create(project_id=project.id, category="c", content="3")

        deleted = constraint_repo.delete_by_project(project.id)
        assert deleted == 3
        assert constraint_repo.list_by_project(project.id) == []


class TestConstraintImportTemplate:
    """import_template: 从模板导入。"""

    def test_import_python_default(self, constraint_repo, project):
        """导入 python_default 模板。"""
        created = constraint_repo.import_template(project.id, "python_default")
        assert len(created) == len(CONSTRAINT_TEMPLATES["python_default"])

        # 验证都存入了数据库
        stored = constraint_repo.list_by_project(project.id)
        assert len(stored) == len(created)

    def test_import_unknown_template(self, constraint_repo, project):
        """导入不存在的模板抛 ValueError。"""
        with pytest.raises(ValueError, match="Unknown constraint template"):
            constraint_repo.import_template(project.id, "nonexistent_template")

    def test_all_templates_importable(self, constraint_repo, project):
        """所有预设模板都可成功导入。"""
        for template_name in CONSTRAINT_TEMPLATES:
            created = constraint_repo.import_template(project.id, template_name)
            assert len(created) > 0
            # 清理
            constraint_repo.delete_by_project(project.id)


class TestConstraintResolveActive:
    """resolve_active: 解析激活的约束。"""

    def test_resolve_always_active(self, constraint_repo, project):
        """trigger_pattern 为 None 或 'always' 的约束始终激活。"""
        constraint_repo.create(
            project_id=project.id, category="a", content="always", trigger_pattern=None
        )
        constraint_repo.create(
            project_id=project.id, category="b", content="explicit", trigger_pattern="always"
        )

        active = constraint_repo.resolve_active(project.id)
        assert len(active) == 2

    def test_resolve_file_pattern_match(self, constraint_repo, project):
        """文件模式匹配当前文件。"""
        constraint_repo.create(
            project_id=project.id, category="py", content="python", trigger_pattern="*.py"
        )
        constraint_repo.create(
            project_id=project.id, category="js", content="javascript", trigger_pattern="*.js"
        )

        # 匹配 Python 文件
        active = constraint_repo.resolve_active(project.id, current_file="src/main.py")
        assert len(active) == 1
        assert active[0].content == "python"

        # 匹配 JS 文件
        active = constraint_repo.resolve_active(project.id, current_file="app.js")
        assert len(active) == 1
        assert active[0].content == "javascript"

    def test_resolve_no_file_no_pattern_match(self, constraint_repo, project):
        """无 current_file 时只返回 always 约束。"""
        constraint_repo.create(
            project_id=project.id, category="always", content="global", trigger_pattern="always"
        )
        constraint_repo.create(
            project_id=project.id, category="file", content="specific", trigger_pattern="*.py"
        )

        active = constraint_repo.resolve_active(project.id, current_file=None)
        assert len(active) == 1
        assert active[0].content == "global"

    def test_resolve_disabled_not_returned(self, constraint_repo, project):
        """禁用的约束不返回。"""
        c = constraint_repo.create(
            project_id=project.id, category="test", content="disabled", trigger_pattern="always"
        )
        constraint_repo.update(c.id, enabled=False)

        active = constraint_repo.resolve_active(project.id)
        assert len(active) == 0

    def test_resolve_sorted_by_priority(self, constraint_repo, project):
        """结果按优先级降序排列。"""
        constraint_repo.create(
            project_id=project.id, category="low", content="low", priority=3
        )
        constraint_repo.create(
            project_id=project.id, category="high", content="high", priority=9
        )

        active = constraint_repo.resolve_active(project.id)
        assert active[0].content == "high"
        assert active[1].content == "low"
