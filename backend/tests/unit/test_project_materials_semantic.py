"""L4 语义检索注入 build_project_materials_block_semantic 单元测试。

覆盖:
- 语义检索成功 → 渲染 chunks (按 material_id 分组, 分数标注)
- 语义检索空结果 → 降级全量注入
- indexer 不可用 → 降级全量注入
- 异常 → 降级全量注入
- 预算控制 TOTAL_CHAR_CAP 生效
- _fallback_full_injection 独立路径
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.chat.project_context import (
    TOTAL_CHAR_CAP,
    build_project_materials_block_semantic,
    _fallback_full_injection,
)

pytestmark = [pytest.mark.unit]


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_result(material_id, chunk_index, content, score):
    """构造 SemanticSearchResult mock。"""
    r = MagicMock()
    r.material_id = material_id
    r.chunk_index = chunk_index
    r.content = content
    r.score = score
    r.project_id = "proj-1"
    return r


def _make_material(id="mat-1", content="test content"):
    """构造 ProjectMaterial mock (用于全量注入降级)。"""
    m = MagicMock()
    m.id = id
    m.content = content
    m.enabled = True
    m.status = "ready"
    m.source_message_id = None
    return m


# ── 语义检索成功路径 ─────────────────────────────────────────────────────────


class TestSemanticSuccess:
    def test_renders_chunks_with_header(self):
        result = _make_result("mat-1", 0, "relevant chunk", 0.85)
        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.return_value = [result]

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ):
            output = build_project_materials_block_semantic("proj-1", "query")

        assert "项目资料" in output
        assert "mat-1" in output
        assert "relevant chunk" in output
        assert "relevance=0.85" in output
        assert "1 chunks" in output

    def test_groups_chunks_by_material_id(self):
        """同一资料的多个 chunks 应合并展示。"""
        r1 = _make_result("mat-1", 0, "chunk A", 0.9)
        r2 = _make_result("mat-1", 1, "chunk B", 0.8)
        r3 = _make_result("mat-2", 0, "chunk C", 0.7)

        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.return_value = [r1, r2, r3]

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ):
            output = build_project_materials_block_semantic("proj-1", "query")

        # mat-1 的 header 应标注 2 chunks
        assert "2 chunks" in output
        assert "chunk A" in output
        assert "chunk B" in output
        # mat-2 的 header 应标注 1 chunk
        assert "1 chunks" in output
        assert "chunk C" in output

    def test_uses_max_score_for_group(self):
        """同一资料多 chunks 时 header 应显示最高分数。"""
        r1 = _make_result("mat-1", 0, "a", 0.5)
        r2 = _make_result("mat-1", 1, "b", 0.95)

        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.return_value = [r1, r2]

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ):
            output = build_project_materials_block_semantic("proj-1", "query")

        assert "relevance=0.95" in output


# ── 降级路径 ─────────────────────────────────────────────────────────────────


class TestFallback:
    def test_indexer_not_available_falls_back(self):
        mock_indexer = MagicMock()
        mock_indexer.available = False

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ), patch(
            "backend.data.project_material_repo.ProjectMaterialRepository"
        ) as mock_repo:
            mock_repo.return_value.get_active_materials_for_project.return_value = [
                _make_material()
            ]
            output = build_project_materials_block_semantic("proj-1", "query")

        assert "test content" in output
        mock_repo.return_value.get_active_materials_for_project.assert_called_once_with(
            "proj-1"
        )

    def test_empty_results_falls_back(self):
        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.return_value = []

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ), patch(
            "backend.data.project_material_repo.ProjectMaterialRepository"
        ) as mock_repo:
            mock_repo.return_value.get_active_materials_for_project.return_value = [
                _make_material()
            ]
            output = build_project_materials_block_semantic("proj-1", "query")

        assert "test content" in output

    def test_exception_falls_back(self):
        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.side_effect = RuntimeError("vec table corrupt")

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ), patch(
            "backend.data.project_material_repo.ProjectMaterialRepository"
        ) as mock_repo:
            mock_repo.return_value.get_active_materials_for_project.return_value = [
                _make_material()
            ]
            output = build_project_materials_block_semantic("proj-1", "query")

        # 降级成功
        assert "test content" in output

    def test_fallback_also_fails_returns_empty(self):
        """降级路径也失败时返回空字符串。"""
        mock_indexer = MagicMock()
        mock_indexer.available = False

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ), patch(
            "backend.data.project_material_repo.ProjectMaterialRepository"
        ) as mock_repo:
            mock_repo.return_value.get_active_materials_for_project.side_effect = (
                RuntimeError("db down")
            )
            output = build_project_materials_block_semantic("proj-1", "query")

        assert output == ""


# ── 预算控制 ──────────────────────────────────────────────────────────────────


class TestBudget:
    def test_total_char_cap_truncates(self):
        """合并后的内容超过 TOTAL_CHAR_CAP 时应截断。"""
        # 创建一个超过预算的大 chunk
        big_content = "x" * (TOTAL_CHAR_CAP + 1000)
        result = _make_result("mat-1", 0, big_content, 0.9)

        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.return_value = [result]

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ):
            output = build_project_materials_block_semantic("proj-1", "query")

        # 输出总长不应远超 TOTAL_CHAR_CAP + header 开销
        assert len(output) < TOTAL_CHAR_CAP + 500

    def test_excluded_count_noted(self):
        """超出预算的资料应在末尾注明。"""
        # 第一个 chunk 占满预算
        r1 = _make_result("mat-1", 0, "x" * TOTAL_CHAR_CAP, 0.9)
        r2 = _make_result("mat-2", 0, "should be excluded", 0.8)

        mock_indexer = MagicMock()
        mock_indexer.available = True
        mock_indexer.search.return_value = [r1, r2]

        with patch(
            "backend.services.project_material_indexer.ProjectMaterialIndexer",
            return_value=mock_indexer,
        ):
            output = build_project_materials_block_semantic("proj-1", "query")

        assert "超出预算被排除" in output
        assert "should be excluded" not in output


# ── _fallback_full_injection ──────────────────────────────────────────────────


class TestFallbackFullInjection:
    def test_returns_full_block(self):
        with patch(
            "backend.data.project_material_repo.ProjectMaterialRepository"
        ) as mock_repo:
            mock_repo.return_value.get_active_materials_for_project.return_value = [
                _make_material("mat-1", "content A"),
                _make_material("mat-2", "content B"),
            ]
            output = _fallback_full_injection("proj-1")

        assert "content A" in output
        assert "content B" in output

    def test_returns_empty_on_error(self):
        with patch(
            "backend.data.project_material_repo.ProjectMaterialRepository"
        ) as mock_repo:
            mock_repo.return_value.get_active_materials_for_project.side_effect = (
                RuntimeError("fail")
            )
            output = _fallback_full_injection("proj-1")

        assert output == ""
