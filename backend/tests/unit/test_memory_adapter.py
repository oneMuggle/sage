"""Unit tests for MemoryAdapter

测试 MemoryAdapter 的三个核心方法:
- retrieve(): 检索记忆
- store(): 存储记忆
- compress(): 压缩工作记忆
"""

from unittest.mock import Mock

import pytest

from backend.adapters.out.memory.adapter import MemoryAdapter
from backend.domain.memory import MemoryContext
from backend.memory import MemoryManager

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_memory_manager():
    """创建 mock 的 MemoryManager"""
    manager = Mock(spec=MemoryManager)
    manager.working = Mock()
    manager.working.total_tokens = 1000
    manager.working.messages = []
    manager.working.get_context = Mock(return_value=[])
    return manager


@pytest.fixture
def mock_consolidation():
    """创建 mock 的 ConsolidationPipeline"""
    return Mock()


@pytest.fixture
def adapter(mock_memory_manager, mock_consolidation):
    """创建 MemoryAdapter 实例"""
    adapter = MemoryAdapter(mock_memory_manager)
    adapter.consolidation = mock_consolidation  # 替换为 mock
    return adapter


class TestMemoryAdapterRetrieve:
    """测试 retrieve() 方法"""

    @pytest.mark.asyncio
    async def test_retrieve_returns_memory_context(self, adapter, mock_memory_manager):
        """测试 retrieve() 返回 MemoryContext"""
        # Arrange: 设置 mock 返回值
        mock_memory_manager.recall.return_value = {
            "working": [{"role": "user", "content": "你好"}],
            "episodic": [{"content": "用户偏好", "summary": "偏好"}],
            "semantic": [{"content": "Python 知识", "summary": "知识"}],
        }

        # Act: 调用 retrieve()
        context = await adapter.retrieve("测试查询", "session-123", limit=5)

        # Assert
        assert isinstance(context, MemoryContext)
        assert len(context.working) == 1
        assert context.working[0]["content"] == "你好"
        # RRF 融合后：episodic + semantic 合并为分层结果
        all_items = context.episodic + context.semantic + context.core
        assert len(all_items) >= 1
        summaries = [item.get("summary") for item in all_items]
        assert "偏好" in summaries or "知识" in summaries

    @pytest.mark.asyncio
    async def test_retrieve_calls_memory_manager_recall(self, adapter, mock_memory_manager):
        """测试 retrieve() 调用了 MemoryManager.recall()"""
        # Arrange
        mock_memory_manager.recall.return_value = {"working": [], "episodic": [], "semantic": []}

        # Act
        await adapter.retrieve("火锅", "session-456", limit=3)

        # Assert
        mock_memory_manager.recall.assert_called_once_with("火锅", limit=3)

    @pytest.mark.asyncio
    async def test_retrieve_handles_empty_results(self, adapter, mock_memory_manager):
        """测试 retrieve() 处理空结果"""
        # Arrange
        mock_memory_manager.recall.return_value = {}

        # Act
        context = await adapter.retrieve("查询", "session-789")

        # Assert
        assert isinstance(context, MemoryContext)
        assert context.working == []
        assert context.episodic == []
        assert context.semantic == []
        assert not context.has_memories


class TestMemoryAdapterStore:
    """测试 store() 方法"""

    @pytest.mark.asyncio
    async def test_store_calls_memory_manager_memorize(self, adapter, mock_memory_manager):
        """测试 store() 调用了 MemoryManager.memorize()"""
        # Arrange
        mock_memory_manager.memorize.return_value = "memory-id-123"

        # Act
        memory_id = await adapter.store(
            content="用户喜欢吃火锅",
            session_id="session-123",
            importance=7,
            tags=["preference", "food"],
        )

        # Assert
        mock_memory_manager.memorize.assert_called_once_with(
            content="用户喜欢吃火锅",
            importance=7,
            metadata={"session_id": "session-123", "tags": ["preference", "food"]},
        )
        assert memory_id == "memory-id-123"

    @pytest.mark.asyncio
    async def test_store_returns_empty_string_for_working_memory(
        self, adapter, mock_memory_manager
    ):
        """测试 store() 对于工作记忆返回空字符串"""
        # Arrange: memorize() 返回 None 表示存储到工作记忆
        mock_memory_manager.memorize.return_value = None

        # Act
        memory_id = await adapter.store(content="临时信息", session_id="session-123", importance=3)

        # Assert
        assert memory_id == ""

    @pytest.mark.asyncio
    async def test_store_uses_default_importance(self, adapter, mock_memory_manager):
        """测试 store() 使用默认的 importance=5"""
        # Arrange
        mock_memory_manager.memorize.return_value = "memory-id-456"

        # Act
        await adapter.store(content="一般信息", session_id="session-123")

        # Assert
        call_kwargs = mock_memory_manager.memorize.call_args[1]
        assert call_kwargs["importance"] == 5

    @pytest.mark.asyncio
    async def test_store_uses_empty_tags_when_none(self, adapter, mock_memory_manager):
        """测试 store() 当 tags=None 时使用空列表"""
        # Arrange
        mock_memory_manager.memorize.return_value = "memory-id-789"

        # Act
        await adapter.store(content="无标签信息", session_id="session-123", tags=None)

        # Assert
        call_kwargs = mock_memory_manager.memorize.call_args[1]
        assert call_kwargs["metadata"]["tags"] == []


class TestMemoryAdapterCompress:
    """测试 compress() 方法"""

    @pytest.mark.asyncio
    async def test_compress_when_tokens_exceed_threshold(
        self, adapter, mock_memory_manager, mock_consolidation
    ):
        """测试当 Token 超过阈值时执行压缩"""
        # Arrange: 设置 Token 数量为 4000 (> 3000)
        mock_memory_manager.working.total_tokens = 4000

        # Act
        await adapter.compress("session-123")

        # Assert: 验证 consolidation.consolidate() 被调用
        mock_consolidation.consolidate.assert_called_once_with(
            mock_memory_manager, session_id="session-123"
        )

    @pytest.mark.asyncio
    async def test_compress_skips_when_tokens_low(
        self, adapter, mock_memory_manager, mock_consolidation
    ):
        """测试当 Token 数量低时跳过压缩"""
        # Arrange: 设置 Token 数量为 1000 (<= 3000)
        mock_memory_manager.working.total_tokens = 1000

        # Act
        await adapter.compress("session-123")

        # Assert: 验证 consolidation.consolidate() 未被调用
        mock_consolidation.consolidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_compress_at_exact_threshold(
        self, adapter, mock_memory_manager, mock_consolidation
    ):
        """测试 Token 数量等于阈值时不压缩"""
        # Arrange: 设置 Token 数量为 3000 (== 3000)
        mock_memory_manager.working.total_tokens = 3000

        # Act
        await adapter.compress("session-123")

        # Assert: 阈值是 > 3000,所以等于时不压缩
        mock_consolidation.consolidate.assert_not_called()


class TestMemoryContextIntegration:
    """测试 MemoryContext 集成"""

    def test_memory_context_format(self):
        """测试 MemoryContext.format() 方法"""
        # Arrange
        context = MemoryContext(
            working=[
                {"role": "user", "content": "我想吃火锅"},
                {"role": "assistant", "content": "好的,我帮你找火锅店"},
            ],
            episodic=[{"content": "用户喜欢吃火锅", "summary": "饮食偏好"}],
            semantic=[{"content": "海底捞是知名火锅连锁", "summary": "火锅品牌"}],
        )

        # Act
        formatted = context.format()

        # Assert
        assert "【当前对话】" in formatted
        assert "[user]: 我想吃火锅" in formatted
        assert "[assistant]: 好的,我帮你找火锅店" in formatted
        # 新版 format 合并为 【相关记忆】
        assert "【相关记忆】" in formatted
        assert "饮食偏好" in formatted or "火锅" in formatted
        assert "火锅品牌" in formatted or "海底捞" in formatted

    def test_memory_context_has_memories_true(self):
        """测试 MemoryContext.has_memories 为 True"""
        context = MemoryContext(
            working=[{"role": "user", "content": "你好"}], episodic=[], semantic=[]
        )
        assert context.has_memories is True

    def test_memory_context_has_memories_false(self):
        """测试 MemoryContext.has_memories 为 False"""
        context = MemoryContext(working=[], episodic=[], semantic=[])
        assert context.has_memories is False
