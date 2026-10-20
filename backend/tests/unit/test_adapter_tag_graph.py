"""Unit tests for tag_graph integration into MemoryAdapter

测试 Phase 2 tag_graph 接入：
- _extract_query_tags(): 从 query 提取标签
- get_tag_graph(): 懒加载单例
- build_tag_graph_async(): 异步构建
- MemoryAdapter.retrieve(): 第三路召回集成
"""

from unittest.mock import Mock, patch

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter, _extract_query_tags
from backend.domain.memory import MemoryContext
from backend.memory import MemoryManager

pytestmark = pytest.mark.unit


# ============================================================================
# Query tag extraction helper
# ============================================================================


class TestExtractQueryTags:
    """测试 _extract_query_tags() 辅助函数"""

    def test_extracts_chinese_tokens(self):
        """中文 query 提取有效 token"""
        tags = _extract_query_tags("Python 编程技巧")
        assert "python" in tags or "Python" in tags
        assert any("编程" in t or "技巧" in t for t in tags)

    def test_filters_stopwords(self):
        """停用词被过滤（的、了、是、在）"""
        tags = _extract_query_tags("用户喜欢吃火锅")
        for sw in ["的", "了", "是", "在", "和", "与"]:
            assert sw not in tags

    def test_filters_short_tokens(self):
        """长度 < 2 的 token 被过滤"""
        tags = _extract_query_tags("a b c 编程")
        for t in tags:
            assert len(t) >= 2

    def test_respects_max_tags(self):
        """max_tags 限制返回数量"""
        tags = _extract_query_tags("Python fastapi docker kubernetes git", max_tags=3)
        assert len(tags) <= 3

    def test_empty_query_returns_empty(self):
        """空 query 返回空列表"""
        assert _extract_query_tags("") == []
        assert _extract_query_tags("   ") == []


# ============================================================================
# get_tag_graph() 单例
# ============================================================================


class TestGetTagGraph:
    """测试 get_tag_graph() 懒加载单例"""

    def test_returns_tag_cooccurrence_graph(self):
        """返回 TagCooccurrenceGraph 实例"""
        import backend.memory.tag_graph as tg_module
        from backend.memory.tag_graph import TagCooccurrenceGraph, get_tag_graph

        original = tg_module._graph
        tg_module._graph = None
        tg_module._graph_built = False

        try:
            graph = get_tag_graph()
            assert isinstance(graph, TagCooccurrenceGraph)
            assert graph.total_memories == 0
        finally:
            tg_module._graph = original

    def test_returns_same_instance(self):
        """多次调用返回同一实例"""
        import backend.memory.tag_graph as tg_module
        from backend.memory.tag_graph import get_tag_graph

        original = tg_module._graph
        tg_module._graph = None

        try:
            g1 = get_tag_graph()
            g2 = get_tag_graph()
            assert g1 is g2
        finally:
            tg_module._graph = original


# ============================================================================
# Async background graph construction
# ============================================================================


class TestBuildTagGraphAsync:
    """测试 build_tag_graph_async() 后台构建"""

    def test_builds_in_background(self):
        """后台线程构建图谱"""
        import time

        import backend.memory.tag_graph as tg_module
        from backend.memory.tag_graph import build_tag_graph_async, get_tag_graph

        original_graph = tg_module._graph
        original_built = tg_module._graph_built
        tg_module._graph = None
        tg_module._graph_built = False

        episodic = Mock()
        episodic.get_recent.return_value = [
            {"id": "m1", "tags": '["python", "fastapi"]'},
            {"id": "m2", "tags": '["python", "docker"]'},
        ]
        semantic = Mock()
        semantic.get_recent.return_value = [
            {"id": "m3", "tags": '["fastapi", "api"]'},
        ]

        try:
            build_tag_graph_async(episodic, semantic)
            time.sleep(0.5)

            graph = get_tag_graph()
            assert graph.total_memories == 3
            assert "python" in graph.tag_cooccurrence
        finally:
            tg_module._graph = original_graph
            tg_module._graph_built = original_built

    def test_idempotent(self):
        """重复调用不重复构建"""
        import backend.memory.tag_graph as tg_module
        from backend.memory.tag_graph import build_tag_graph_async

        original_built = tg_module._graph_built
        tg_module._graph_built = False

        episodic = Mock()
        episodic.get_recent.return_value = []
        semantic = Mock()
        semantic.get_recent.return_value = []

        try:
            build_tag_graph_async(episodic, semantic)
            build_tag_graph_async(episodic, semantic)
            assert tg_module._graph_built is True
        finally:
            tg_module._graph_built = original_built


# ============================================================================
# MemoryAdapter.retrieve() 集成 tag_graph
# ============================================================================


class TestRetrieveTagGraphIntegration:
    """测试 retrieve() 的 tag_graph 第三路召回"""

    @pytest.fixture()
    def mock_memory_manager(self):
        manager = Mock(spec=MemoryManager)
        manager.working = Mock()
        manager.working.total_tokens = 1000
        manager.working.total_tokens_for = Mock(return_value=1000)
        manager.working.messages = []
        manager.working.get_context = Mock(return_value=[])
        return manager

    @pytest.fixture()
    def adapter(self, mock_memory_manager):
        adapter = MemoryAdapter(mock_memory_manager)
        adapter.consolidation = Mock()
        return adapter

    @pytest.mark.asyncio()
    async def test_retrieve_includes_tag_graph_hits(self, adapter, mock_memory_manager):
        """tag_graph 命中的记忆被合并到 fused"""
        mock_memory_manager.recall.return_value = {
            "working": [],
            "episodic": [],
            "semantic": [],
        }

        mock_graph = Mock()
        mock_graph.total_memories = 10
        mock_graph.query.return_value = [
            {"memory_id": "tg-mem-1", "score": 2.5, "matched_tags": ["python"]},
        ]

        mock_memory_manager.episodic = Mock()
        mock_memory_manager.episodic.get_by_id.return_value = {
            "id": "tg-mem-1",
            "content": "Python 技巧",
            "importance": 5,
            "memory_type": "episodic",
        }
        mock_memory_manager.semantic = Mock()
        mock_memory_manager.semantic.get_by_id.return_value = None

        with (
            patch(
                "backend.memory.tag_graph.get_tag_graph",
                return_value=mock_graph,
            ),
            patch(
                "backend.adapters.out.memory.adapter._extract_query_tags",
                return_value=["python"],
            ),
        ):
            context = await adapter.retrieve("Python", "session-1", limit=5)

        all_ids = (
            [m.get("id") for m in context.episodic]
            + [m.get("id") for m in context.semantic]
        )
        assert "tg-mem-1" in all_ids

    @pytest.mark.asyncio()
    async def test_retrieve_skips_tag_graph_when_empty(self, adapter, mock_memory_manager):
        """tag_graph 未构建（total_memories==0）时跳过"""
        mock_memory_manager.recall.return_value = {
            "working": [],
            "episodic": [{"id": "e1", "content": "test", "importance": 5}],
            "semantic": [],
        }
        mock_memory_manager.episodic = Mock()
        mock_memory_manager.episodic.get_by_id.return_value = None
        mock_memory_manager.semantic = Mock()

        mock_graph = Mock()
        mock_graph.total_memories = 0

        with (
            patch(
                "backend.memory.tag_graph.get_tag_graph",
                return_value=mock_graph,
            ),
            patch(
                "backend.adapters.out.memory.adapter._extract_query_tags",
                return_value=["python"],
            ),
        ):
            context = await adapter.retrieve("test", "session-1", limit=5)

        assert isinstance(context, MemoryContext)
