"""project_material_repo 单元测试 (M3 项目上下文沉淀, 2026-09-15)。

TDD: 先写失败测试, 再实现。覆盖:
- add: 新增资料, 计算 content_hash, 状态默认 ready (添加即生效, P0 修复 2026-09-20)
- add (status=): 显式 pending_index 保留给异步索引; 非法 status 抛 ValueError
- add (duplicate): 同 project+hash 幂等, 返回已有行
- add (duplicate, failed): 已有行为 failed 时按本次 status 复活并清空 error_message
- list_by_project: 按项目列出资料
- remove: 删除资料
- mark_ready: 标记索引完成
- mark_failed: 标记索引失败 + error_message
- get_active_materials_for_project: 返回 ready 状态的资料 (上下文注入用)

使用 conftest.py 的 autouse ``setup_test_db`` fixture 创建临时数据库,
无需手动管理 DB 生命周期。
"""

from __future__ import annotations

import pytest

from backend.data.project_material_repo import (
    ProjectMaterialRepository,
)
from backend.data.project_repo import ProjectRepository


@pytest.fixture()
def project(tmp_path):
    """创建一个测试项目（目录必须存在于磁盘）。"""
    # ProjectRepository.register 调用 validate_workspace, 目录必须存在
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()
    return ProjectRepository().register(str(project_dir))


@pytest.fixture()
def other_project(tmp_path):
    """第二个项目, 用于隔离测试。"""
    project_dir = tmp_path / "other-project"
    project_dir.mkdir()
    return ProjectRepository().register(str(project_dir))


@pytest.fixture()
def material_repo(setup_test_db):
    """ProjectMaterialRepository 实例 (依赖 autouse setup_test_db)。"""
    return ProjectMaterialRepository()


class TestProjectMaterialAdd:
    """add: 新增资料。"""

    def test_add_creates_material_ready_by_default(
        self, material_repo, project
    ):
        """新增资料默认 ready (无异步索引, 添加即注入), content_hash 自动计算。"""
        material = material_repo.add(
            project_id=project.id,
            content="# Test content\nSome text",
            source_message_id="msg_123",
        )
        assert material.project_id == project.id
        assert material.source_message_id == "msg_123"
        assert material.status == "ready"
        assert material.error_message is None
        assert material.content_hash  # SHA-256 hex
        assert material.wiki_page_path is None
        assert material.created_at > 0

    def test_add_with_explicit_pending_status(self, material_repo, project):
        """显式 status=pending_index 保留给未来的异步索引管线。"""
        material = material_repo.add(
            project.id, "# Async indexed", "msg_1", status="pending_index"
        )
        assert material.status == "pending_index"
        assert material_repo.get_active_materials_for_project(project.id) == []

    def test_add_rejects_invalid_status(self, material_repo, project):
        """非法 status 直接拒绝, 不写库。"""
        with pytest.raises(ValueError, match="Invalid material status"):
            material_repo.add(project.id, "# Bad", "msg_1", status="indexed")
        assert material_repo.list_by_project(project.id) == []

    def test_add_dedup_by_project_and_hash(self, material_repo, project):
        """同 project+hash 幂等, 返回已有行而非新建。"""
        content = "# Duplicate content"
        m1 = material_repo.add(project.id, content, "msg_1")
        m2 = material_repo.add(project.id, content, "msg_2")
        assert m1.id == m2.id
        assert m1.content_hash == m2.content_hash

    def test_add_revives_failed_duplicate(self, material_repo, project):
        """已有行 failed 时重复添加 = 重试: 同 id, 状态复活, error_message 清空。"""
        content = "# Retry me"
        m1 = material_repo.add(project.id, content, "msg_1")
        assert material_repo.mark_failed(m1.id, "index error") is True
        m2 = material_repo.add(project.id, content, "msg_2")
        assert m2.id == m1.id
        assert m2.status == "ready"
        assert m2.error_message is None
        assert len(material_repo.list_by_project(project.id)) == 1

    def test_add_dedup_keeps_pending_row_untouched(self, material_repo, project):
        """已有行 pending_index (索引中) 时重复添加不改状态。"""
        content = "# Still indexing"
        m1 = material_repo.add(project.id, content, "msg_1", status="pending_index")
        m2 = material_repo.add(project.id, content, "msg_2")
        assert m2.id == m1.id
        assert m2.status == "pending_index"

    def test_add_different_content_creates_separate(
        self, material_repo, project
    ):
        """不同 content → 不同 hash → 不同行。"""
        m1 = material_repo.add(project.id, "# Content A", "msg_1")
        m2 = material_repo.add(project.id, "# Content B", "msg_2")
        assert m1.id != m2.id
        assert m1.content_hash != m2.content_hash


class TestProjectMaterialList:
    """list_by_project: 按项目列出资料。"""

    def test_list_empty(self, material_repo, project):
        """无资料时返回空列表。"""
        materials = material_repo.list_by_project(project.id)
        assert materials == []

    def test_list_returns_all_for_project(
        self, material_repo, project
    ):
        """返回项目下所有资料, 按 created_at DESC。"""
        # 使用显式 timestamp 避免同一毫秒内并列——并列时 SQL id DESC tiebreaker
        # 与插入顺序无关 (UUID 无序), 不能稳定重现"新→旧"语义
        m1 = material_repo.add(project.id, "# First", "msg_1", now_ms=1000)
        m2 = material_repo.add(project.id, "# Second", "msg_2", now_ms=2000)
        materials = material_repo.list_by_project(project.id)
        assert len(materials) == 2
        # 新的在前
        assert materials[0].id == m2.id
        assert materials[1].id == m1.id

    def test_list_filters_by_project(
        self, material_repo, project, other_project
    ):
        """不同项目的资料互不可见。"""
        material_repo.add(project.id, "# Project A", "msg_1")
        material_repo.add(other_project.id, "# Project B", "msg_2")
        materials = material_repo.list_by_project(project.id)
        assert len(materials) == 1
        assert materials[0].project_id == project.id


class TestProjectMaterialRemove:
    """remove: 删除资料。"""

    def test_remove_existing(self, material_repo, project):
        """删除存在的资料返回 True。"""
        material = material_repo.add(project.id, "# To delete", "msg_1")
        removed = material_repo.remove(material.id)
        assert removed is True
        assert material_repo.list_by_project(project.id) == []

    def test_remove_nonexistent(self, material_repo):
        """删除不存在的资料返回 False。"""
        removed = material_repo.remove("nonexistent_id")
        assert removed is False


class TestProjectMaterialStatus:
    """mark_ready / mark_failed: 状态转换。"""

    def test_mark_ready(self, material_repo, project):
        """标记索引完成, 状态变 ready, wiki_page_path 可选。"""
        material = material_repo.add(
            project.id, "# Content", "msg_1", status="pending_index"
        )
        assert material.status == "pending_index"
        updated = material_repo.mark_ready(
            material.id, wiki_page_path="/wiki/page.md"
        )
        assert updated is True
        material_after = material_repo.list_by_project(project.id)[0]
        assert material_after.status == "ready"
        assert material_after.wiki_page_path == "/wiki/page.md"

    def test_mark_failed(self, material_repo, project):
        """标记索引失败, 状态变 failed, error_message 记录。"""
        material = material_repo.add(project.id, "# Content", "msg_1")
        updated = material_repo.mark_failed(material.id, "LLM timeout")
        assert updated is True
        material_after = material_repo.list_by_project(project.id)[0]
        assert material_after.status == "failed"
        assert material_after.error_message == "LLM timeout"

    def test_mark_ready_nonexistent(self, material_repo):
        """标记不存在的资料返回 False。"""
        assert material_repo.mark_ready("nonexistent") is False


class TestProjectMaterialGetActive:
    """get_active_materials_for_project: 返回 ready 状态资料 (上下文注入)。"""

    def test_get_active_returns_only_ready(
        self, material_repo, project
    ):
        """只返回 status=ready 的资料, 忽略 pending/failed。"""
        m1 = material_repo.add(project.id, "# Ready", "msg_1")  # 默认 ready
        material_repo.add(project.id, "# Pending", "msg_2", status="pending_index")
        m3 = material_repo.add(project.id, "# Failed", "msg_3")
        material_repo.mark_failed(m3.id, "error")
        active = material_repo.get_active_materials_for_project(project.id)
        assert len(active) == 1
        assert active[0].id == m1.id
        assert active[0].status == "ready"

    def test_get_active_empty_when_no_ready(
        self, material_repo, project
    ):
        """无 ready 资料时返回空列表。"""
        material_repo.add(project.id, "# Pending", "msg_1", status="pending_index")
        active = material_repo.get_active_materials_for_project(project.id)
        assert active == []

    def test_get_active_ordered_by_created_at_asc(
        self, material_repo, project
    ):
        """返回的资料按 created_at ASC 排序 (旧的先注入)。"""
        m1 = material_repo.add(project.id, "# First", "msg_1", now_ms=1000)
        m2 = material_repo.add(project.id, "# Second", "msg_2", now_ms=2000)
        active = material_repo.get_active_materials_for_project(project.id)
        assert len(active) == 2
        # 旧的在前——按注入顺序
        assert active[0].id == m1.id
        assert active[1].id == m2.id


    def test_set_enabled_filters_active_materials(
        self, material_repo, project
    ):
        """set_enabled(False) 暂停注入，set_enabled(True) 恢复注入。"""
        m1 = material_repo.add(project.id, "# Source 1", "msg_1", now_ms=1000)
        m2 = material_repo.add(project.id, "# Source 2", "msg_2", now_ms=2000)
        assert m1.enabled is True
        assert m2.enabled is True

        toggled = material_repo.set_enabled(m1.id, False)
        assert toggled is not None
        assert toggled.enabled is False

        active = material_repo.get_active_materials_for_project(project.id)
        assert [m.id for m in active] == [m2.id]

        restored = material_repo.set_enabled(m1.id, True)
        assert restored is not None
        assert restored.enabled is True
        active_after = material_repo.get_active_materials_for_project(project.id)
        assert [m.id for m in active_after] == [m1.id, m2.id]
