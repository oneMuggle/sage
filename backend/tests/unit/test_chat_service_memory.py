"""Unit tests for ChatService memory integration

测试 ChatService 的记忆集成功能:
- 对话前检索记忆
- 记忆注入到 system prompt
- 对话后存储记忆
- 压缩工作记忆
"""
from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.services.chat_service import ChatService
from backend.domain.memory import MemoryContext
from backend.domain.message import Message, Role
from backend.ports.memory import MemoryPort

pytestmark = pytest.mark.unit


@pytest.fixture()
def mock_llm():
    """创建 mock 的 LLMPort"""
    llm = Mock()
    # 返回一个 Message 对象,内容足够长 (>100 字符),以触发记忆存储
    llm.chat = AsyncMock(
        return_value=Message(
            role=Role.ASSISTANT,
            content="好的,我理解您想吃火锅。成都确实有很多不错的火锅店,海底捞是一个很好的选择,服务一流。",
        )
    )
    return llm


@pytest.fixture()
def mock_tools():
    """创建 mock 的 ToolPort"""
    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    return tools


@pytest.fixture()
def mock_storage():
    """创建 mock 的 StoragePort"""
    storage = Mock()
    storage.append_message = AsyncMock()
    storage.get_messages = AsyncMock(return_value=[])
    return storage


@pytest.fixture()
def mock_metrics():
    """创建 mock 的 MetricPort"""
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    return metrics


@pytest.fixture()
def mock_events():
    """创建 mock 的 EventPort"""
    events = Mock()
    events.emit = Mock()
    return events


@pytest.fixture()
def mock_memory():
    """创建 mock 的 MemoryPort"""
    memory = Mock(spec=MemoryPort)
    memory.retrieve = AsyncMock(return_value=MemoryContext(working=[], episodic=[], semantic=[]))
    memory.store = AsyncMock(return_value="memory-id-123")
    memory.compress = AsyncMock()
    return memory


@pytest.fixture()
def chat_service_with_memory(
    mock_llm, mock_tools, mock_storage, mock_metrics, mock_events, mock_memory
):
    """创建带记忆功能的 ChatService 实例"""
    return ChatService(
        llm=mock_llm,
        tools=mock_tools,
        skills=None,
        storage=mock_storage,
        metrics=mock_metrics,
        events=mock_events,
        memory=mock_memory,
    )


@pytest.fixture()
def chat_service_without_memory(
    mock_llm, mock_tools, mock_storage, mock_metrics, mock_events
):
    """创建不带记忆功能的 ChatService 实例 (向后兼容)"""
    return ChatService(
        llm=mock_llm,
        tools=mock_tools,
        skills=None,
        storage=mock_storage,
        metrics=mock_metrics,
        events=mock_events,
        memory=None,
    )


class TestChatServiceMemoryRetrieval:
    """测试记忆检索功能"""

    @pytest.mark.asyncio()
    async def test_chat_service_retrieves_memory_before_chat(
        self, chat_service_with_memory, mock_memory
    ):
        """测试 ChatService 在对话前检索记忆"""
        # Arrange
        user_message = Message(role=Role.USER, content="我想吃火锅")
        mock_memory.retrieve.return_value = MemoryContext(
            working=[],
            episodic=[{"content": "用户喜欢火锅", "summary": "偏好"}],
            semantic=[],
        )

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert
        mock_memory.retrieve.assert_called_once_with(
            query="我想吃火锅",
            session_id="session-123",
            limit=5,
        )

    @pytest.mark.asyncio()
    async def test_chat_service_handles_memory_retrieval_error(
        self, chat_service_with_memory, mock_memory
    ):
        """测试 ChatService 处理记忆检索错误"""
        # Arrange
        user_message = Message(role=Role.USER, content="测试")
        mock_memory.retrieve.side_effect = Exception("数据库错误")

        # Act
        result = await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert
        assert len(result) == 2
        assert result[0].content == "测试"


class TestChatServiceMemoryInjection:
    """测试记忆注入功能"""

    @pytest.mark.asyncio()
    async def test_chat_service_injects_memory_to_system_prompt(
        self, chat_service_with_memory, mock_llm, mock_memory
    ):
        """测试记忆正确注入到 system prompt"""
        # Arrange
        user_message = Message(role=Role.USER, content="我想吃火锅")
        mock_memory.retrieve.return_value = MemoryContext(
            working=[],
            episodic=[{"content": "用户喜欢火锅", "summary": "饮食偏好"}],
            semantic=[{"content": "海底捞是火锅品牌", "summary": "火锅知识"}],
        )

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert 验证 LLM 被调用时包含了记忆上下文
        assert mock_llm.chat.called
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]  # 第一个参数是 messages 列表

        # 找到 system message
        system_msg = next((m for m in messages if m.role == Role.SYSTEM), None)
        assert system_msg is not None

        # 验证 system prompt 包含记忆
        assert "记忆上下文" in system_msg.content

    @pytest.mark.asyncio()
    async def test_chat_service_no_memory_injection_when_empty(
        self, chat_service_with_memory, mock_llm, mock_memory
    ):
        """测试当没有记忆时不注入"""
        # Arrange
        user_message = Message(role=Role.USER, content="你好")
        mock_memory.retrieve.return_value = MemoryContext(working=[], episodic=[], semantic=[])

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert 验证 system prompt 不包含记忆相关内容
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        system_msg = next((m for m in messages if m.role == Role.SYSTEM), None)
        assert system_msg is not None
        assert "记忆上下文" not in system_msg.content


class TestChatServiceMemoryStorage:
    """测试记忆存储功能"""

    @pytest.mark.asyncio()
    async def test_chat_service_stores_memory_after_chat(
        self, chat_service_with_memory, mock_memory, mock_llm
    ):
        """测试对话后自动存储记忆"""
        # Arrange: 创建较长的对话 (>100 字符)
        user_content = "我想吃火锅,请问成都有什么好的火锅店推荐吗?我听说海底捞不错,但是还有其他更好的选择吗?请详细告诉我各家火锅店的特色和地址,以及人均消费是多少,我需要根据预算来选择"
        assistant_content = "好的,我理解您想吃火锅。成都确实有很多不错的火锅店,除了海底捞之外,还有小龙坎、大龙燚、蜀大侠等,这些都是非常受欢迎的火锅店,每家都有特色。小龙坎以麻辣著称,人均消费约100元;大龙燚以牛油锅底闻名,人均消费约120元"

        user_message = Message(role=Role.USER, content=user_content)
        mock_llm.chat.return_value = Message(role=Role.ASSISTANT, content=assistant_content)

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert 验证记忆被存储
        assert mock_memory.store.called
        call_kwargs = mock_memory.store.call_args[1]
        assert call_kwargs["session_id"] == "session-123"
        assert call_kwargs["tags"] == ["conversation"]
        assert "用户" in call_kwargs["content"]
        assert "助手" in call_kwargs["content"]

    @pytest.mark.asyncio()
    async def test_chat_service_detects_preferences(
        self, chat_service_with_memory, mock_memory, mock_llm
    ):
        """测试 ChatService 检测用户偏好并提高 importance"""
        # Arrange: 用户消息包含偏好关键词,且长度超过 100
        user_content = "我喜欢吃火锅,以后记得推荐火锅店给我。我很喜欢四川口味的火锅,特别是麻辣味的,如果可以的话,请推荐一些地道的四川火锅店,最好是在市中心的,环境要好一些,适合朋友聚会"
        user_message = Message(role=Role.USER, content=user_content)

        assistant_content = "好的,我记住了,您喜欢吃火锅,特别是四川麻辣口味的。我会为您推荐一些地道的四川火锅店,比如小龙坎、大龙燚、蜀大侠、电台巷等,这些都是非常受欢迎的连锁店,环境也很好,非常适合朋友聚会和家庭聚餐,人均消费在100到150之间"
        mock_llm.chat.return_value = Message(role=Role.ASSISTANT, content=assistant_content)

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert 验证 importance 被提高
        assert mock_memory.store.called
        call_kwargs = mock_memory.store.call_args[1]
        assert call_kwargs["importance"] == 7  # 偏好关键词触发

    @pytest.mark.asyncio()
    async def test_chat_service_skips_short_conversations(
        self, chat_service_with_memory, mock_memory
    ):
        """测试短对话不存储记忆"""
        # Arrange: 短对话 (<100 字符)
        user_message = Message(role=Role.USER, content="你好")

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert 验证记忆未被存储 (因为对话太短)
        assert not mock_memory.store.called


class TestChatServiceMemoryCompression:
    """测试记忆压缩功能"""

    @pytest.mark.asyncio()
    async def test_chat_service_compresses_working_memory(
        self, chat_service_with_memory, mock_memory
    ):
        """测试对话后压缩工作记忆"""
        # Arrange
        user_message = Message(role=Role.USER, content="测试消息")

        # Act
        await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert 验证压缩被调用
        mock_memory.compress.assert_called_once_with("session-123")

    @pytest.mark.asyncio()
    async def test_chat_service_handles_compression_error(
        self, chat_service_with_memory, mock_memory
    ):
        """测试 ChatService 处理压缩错误"""
        # Arrange
        user_message = Message(role=Role.USER, content="测试")
        mock_memory.compress.side_effect = Exception("压缩失败")

        # Act
        result = await chat_service_with_memory.run_turn("session-123", user_message)

        # Assert
        assert len(result) == 2


class TestChatServiceBackwardCompatibility:
    """测试向后兼容性"""

    @pytest.mark.asyncio()
    async def test_chat_service_works_without_memory(
        self, chat_service_without_memory
    ):
        """测试 ChatService 在没有 memory 时仍能工作"""
        # Arrange
        user_message = Message(role=Role.USER, content="你好")

        # Act
        result = await chat_service_without_memory.run_turn("session-123", user_message)

        # Assert 对话成功
        assert len(result) == 2
        assert result[0].content == "你好"
