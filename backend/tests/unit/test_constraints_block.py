"""build_constraints_block 单元测试 (项目类型分类系统, 2026-09-24)。

覆盖:
- None project_id → 空串
- 无约束 → 空串
- 有约束 → 格式化输出
- 按优先级降序
- 禁用约束不输出
- 总量超限截断

使用 conftest.py 的 autouse ``setup_test_db`` fixture。
"""

from __future__ import annotations

import pytest

from backend.chat.project_context import (
    CONSTRAINTS_HEADER,
    STAGE_MILESTONES_HEADER,
    TOTAL_CHAR_CAP,
    build_constraints_block,
    build_project_stage_milestones_block,
    extract_active_files_from_text,
)
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_milestone_repo import ProjectMilestoneRepository
from backend.data.project_repo import ProjectRepository

pytestmark = [pytest.mark.unit]


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


class TestBuildConstraintsBlock:
    """build_constraints_block: 渲染约束为 system prompt 文本块。"""

    def test_none_project_id_returns_empty(self):
        """None project_id → 空串。"""
        assert build_constraints_block(None) == ""

    def test_empty_project_id_returns_empty(self):
        """空字符串 project_id → 空串。"""
        assert build_constraints_block("") == ""

    def test_no_constraints_returns_empty(self, project):
        """无约束 → 空串。"""
        assert build_constraints_block(project.id) == ""

    def test_single_constraint_renders(self, constraint_repo, project):
        """单条约束正确渲染。"""
        constraint_repo.create(
            project_id=project.id,
            category="coding_style",
            content="使用双引号字符串",
        )
        block = build_constraints_block(project.id)
        assert CONSTRAINTS_HEADER in block
        assert "[coding_style]" in block
        assert "使用双引号字符串" in block

    def test_multiple_constraints_ordered_by_priority(
        self, constraint_repo, project
    ):
        """多条约束按优先级降序排列。"""
        constraint_repo.create(
            project_id=project.id,
            category="low",
            content="low priority",
            priority=3,
        )
        constraint_repo.create(
            project_id=project.id,
            category="high",
            content="high priority",
            priority=9,
        )
        constraint_repo.create(
            project_id=project.id,
            category="mid",
            content="mid priority",
            priority=5,
        )
        block = build_constraints_block(project.id)
        lines = block.split("\n")
        # 跳过 header，找约束行
        constraint_lines = [ln for ln in lines if ln.startswith("[")]
        assert len(constraint_lines) == 3
        assert "[high]" in constraint_lines[0]
        assert "[mid]" in constraint_lines[1]
        assert "[low]" in constraint_lines[2]

    def test_disabled_constraints_excluded(self, constraint_repo, project):
        """禁用的约束不输出。"""
        _c1 = constraint_repo.create(
            project_id=project.id,
            category="enabled",
            content="enabled constraint",
        )
        c2 = constraint_repo.create(
            project_id=project.id,
            category="disabled",
            content="disabled constraint",
        )
        constraint_repo.update(c2.id, enabled=False)

        block = build_constraints_block(project.id)
        assert "[enabled]" in block
        assert "[disabled]" not in block

    def test_total_cap_truncation(self, constraint_repo, project):
        """超出 TOTAL_CHAR_CAP 时截断并标注。"""
        # 创建大量约束直到超出预算
        big_content = "x" * 1000
        for i in range(20):  # 20 × 1000 = 20000 > 16000
            constraint_repo.create(
                project_id=project.id,
                category=f"cat_{i}",
                content=big_content,
                priority=10 - i,  # 保证顺序
            )

        block = build_constraints_block(project.id)
        assert CONSTRAINTS_HEADER in block
        # 应该截断并标注
        assert "超出预算" in block or len(block) <= TOTAL_CHAR_CAP + len(CONSTRAINTS_HEADER) + 100

    def test_nonexistent_project_id_returns_empty(self):
        """不存在的 project_id → 空串（无约束）。"""
        block = build_constraints_block("nonexistent-project-id")
        assert block == ""

    def test_active_files_filters_trigger_patterns(self, constraint_repo, project):
        """传入 active_files 时，仅激活 always/* 与匹配当前文件通配符的约束。"""
        constraint_repo.create(
            project_id=project.id,
            category="security",
            content="全局安全红线",
            trigger_pattern="always",
            priority=9,
        )
        constraint_repo.create(
            project_id=project.id,
            category="document_format",
            content="Word 公文排版规范",
            trigger_pattern="*.docx",
            priority=8,
        )
        constraint_repo.create(
            project_id=project.id,
            category="experiment_record",
            content="Notebook 实验记录规范",
            trigger_pattern="*.ipynb",
            priority=8,
        )

        files = extract_active_files_from_text("请帮我审阅 02_编制中工作稿/采购合同.docx 的条款")
        assert files == ["02_编制中工作稿/采购合同.docx"]

        block = build_constraints_block(project.id, active_files=files)
        assert "全局安全红线" in block
        assert "Word 公文排版规范" in block
        assert "(*.docx)" in block
        assert "Notebook 实验记录规范" not in block

    def test_build_project_stage_milestones_block(self, project):
        """渲染项目形态、当前阶段与未完成里程碑。"""
        repo = ProjectRepository()
        repo.update_project_type(project.id, "research")
        repo.update_project_stage(project.id, "writing")
        ms_repo = ProjectMilestoneRepository()
        ms_repo.create(
            project_id=project.id,
            title="完成实验消融对比表",
            stage="writing",
        )
        updated = repo.get(project.id)
        block = build_project_stage_milestones_block(updated)
        assert STAGE_MILESTONES_HEADER in block
        assert "type=research" in block
        assert "stage=writing" in block
        assert "完成实验消融对比表" in block
