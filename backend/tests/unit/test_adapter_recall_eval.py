"""Unit tests for recall_eval integration into MemoryAdapter

测试 Phase 2 recall_eval 接入：
- get_recall_evaluator(): 懒加载单例
- MemoryAdapter.retrieve(): 末尾自动调用 log_retrieval()
"""

from unittest.mock import Mock, patch

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.domain.memory import MemoryContext
from backend.memory import MemoryManager

pytestmark = pytest.mark.unit


# ============================================================================
# get_recall_evaluator() 单例
# ============================================================================


class TestGetRecallEvaluator:
    """测试 get_recall_evaluator() 懒加载单例"""

    def test_returns_recall_evaluator(self):
        """返回 RecallEvaluator 实例"""
        import backend.memory.recall_eval as re_module
        from backend.memory.recall_eval import RecallEvaluator, get_recall_evaluator

        original = re_module._evaluator
        re_module._evaluator = None

        try:
            evaluator = get_recall_evaluator()
            assert isinstance(evaluator, RecallEvaluator)
        finally:
            re_module._evaluator = original

    def test_returns_same_instance(self):
        """多次调用返回同一实例"""
        import backend.memory.recall_eval as re_module
        from backend.memory.recall_eval import get_recall_evaluator

        original = re_module._evaluator
        re_module._evaluator = None

        try:
            e1 = get_recall_evaluator()
            e2 = get_recall_evaluator()
            assert e1 is e2
        finally:
            re_module._evaluator = original


# ============================================================================
# MemoryAdapter.retrieve() 集成 recall_eval
# ============================================================================


class TestRetrieveRecallEvalIntegration:
    """测试 retrieve() 末尾自动调用 recall_eval 日志"""

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
    async def test_retrieve_logs_to_recall_eval(self, adapter, mock_memory_manager):
        """retrieve() 调用 get_recall_evaluator().log_retrieval()"""
        mock_memory_manager.recall.return_value = {
            "working": [],
            "episodic": [{"id": "e1", "content": "test", "importance": 5}],
            "semantic": [],
        }
        mock_memory_manager.episodic = Mock()
        mock_memory_manager.semantic = Mock()

        mock_evaluator = Mock()

        with patch(
            "backend.memory.recall_eval.get_recall_evaluator",
            return_value=mock_evaluator,
        ):
            await adapter.retrieve("test query", "session-abc", limit=5)

        mock_evaluator.log_retrieval.assert_called_once()
        call_kwargs = mock_evaluator.log_retrieval.call_args
        assert call_kwargs.kwargs["query"] == "test query"
        assert call_kwargs.kwargs["session_id"] == "session-abc"

    @pytest.mark.asyncio()
    async def test_retrieve_recall_eval_failure_does_not_block(
        self, adapter, mock_memory_manager
    ):
        """recall_eval 日志失败不阻塞 retrieve() 返回"""
        mock_memory_manager.recall.return_value = {
            "working": [],
            "episodic": [],
            "semantic": [],
        }
        mock_memory_manager.episodic = Mock()
        mock_memory_manager.semantic = Mock()

        with patch(
            "backend.memory.recall_eval.get_recall_evaluator",
            side_effect=RuntimeError("evaluator broken"),
        ):
            context = await adapter.retrieve("test", "session-1", limit=5)

        assert isinstance(context, MemoryContext)
