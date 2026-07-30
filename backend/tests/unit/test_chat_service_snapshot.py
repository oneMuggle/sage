"""WS-C P0-3 / P0-2: ChatService frozen snapshot + 统一记忆写入函数单元测试

覆盖两类行为：

1. **Frozen snapshot**（P0-3）：system prompt 的静态段（身份 / 工具说明
   等不随 turn 变化的部分）在 session 首次 turn 组装后缓存，后续 turn
   复用同一字符串；动态记忆段每 turn 拼接在快照之后。
   - 同一 session 第二次 run_turn 不重新组装静态段（spy 计数 == 1）
   - invalidate_session_snapshot（实例方法 + 模块级函数）触发重建
   - session_id 为 None 时不缓存（走旧路径，每 turn 重新组装）

2. **模块级 ``extract_and_store_memory``**（P0-2 统一写入路径）：
   - enabled=False / memory_port=None → 直接返回 0，不触发提取
   - happy path 返回写入条数，store 透传 session_id / importance / tags
   - extractor / store 抛错被内部吞掉（只 warning，绝不外抛）
"""

from unittest.mock import AsyncMock, Mock

import pytest

from backend.application.services.chat_service import (
    ChatService,
    extract_and_store_memory,
    invalidate_session_snapshot,
)
from backend.domain.memory import MemoryContext
from backend.domain.message import Message, Role
from backend.ports.memory import MemoryPort

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# fixtures（与 test_chat_service_memory.py 同构，保持测试风格一致）
# --------------------------------------------------------------------------- #


@pytest.fixture()
def mock_llm():
    llm = Mock()
    llm.chat = AsyncMock(
        return_value=Message(
            role=Role.ASSISTANT,
            content="好的,我理解您想吃火锅。成都确实有很多不错的火锅店,海底捞是一个很好的选择,服务一流。",
        )
    )
    return llm


@pytest.fixture()
def mock_tools():
    tools = Mock()
    tools.list_tools = Mock(return_value=[])
    return tools


@pytest.fixture()
def mock_storage():
    storage = Mock()
    storage.append_message = AsyncMock()
    storage.get_messages = AsyncMock(return_value=[])
    return storage


@pytest.fixture()
def mock_metrics():
    metrics = Mock()
    metrics.counter = Mock()
    metrics.histogram = Mock()
    metrics.gauge = Mock()
    return metrics


@pytest.fixture()
def mock_events():
    events = Mock()
    events.emit = Mock()
    return events


@pytest.fixture()
def mock_memory():
    memory = Mock(spec=MemoryPort)
    memory.retrieve = AsyncMock(return_value=MemoryContext(working=[], episodic=[], semantic=[]))
    memory.store = AsyncMock(return_value="memory-id-123")
    memory.compress = AsyncMock()
    return memory


@pytest.fixture()
def service(mock_llm, mock_tools, mock_storage, mock_metrics, mock_events, mock_memory):
    return ChatService(
        llm=mock_llm,
        tools=mock_tools,
        skills=None,
        storage=mock_storage,
        metrics=mock_metrics,
        events=mock_events,
        memory=mock_memory,
    )


def _spy_static_build(svc: ChatService):
    """给实例的静态段组装函数装一个计数器（保持返回值不变）。"""
    calls = []
    original = svc._build_static_system_prompt

    def spy():
        calls.append(1)
        return original()

    svc._build_static_system_prompt = spy
    return calls


def _system_content_of(llm_call) -> str:
    """从 mock_llm.chat 的某次调用参数里取出 system message 文本。"""
    messages = llm_call[0][0]
    system_msg = next((m for m in messages if m.role == Role.SYSTEM), None)
    assert system_msg is not None, "LLM 调用缺少 system message"
    return system_msg.content


# --------------------------------------------------------------------------- #
# Frozen snapshot
# --------------------------------------------------------------------------- #


class TestSystemPromptSnapshot:
    def test_static_prompt_uses_tool_port_to_detect_drawio(self, service, mock_tools):
        """静态 prompt 必须通过 ToolPort.list_tools() 检测 drawio 工具。"""
        drawio_tool = Mock()
        drawio_tool.name = "mcp__drawio__render_diagram"
        mock_tools.list_tools.return_value = [drawio_tool]

        static_prompt = service._build_static_system_prompt()

        assert "## 图表生成能力" in static_prompt
        mock_tools.list_tools.assert_called_once_with()

    @pytest.mark.asyncio()
    async def test_second_turn_reuses_static_segment(self, service, mock_llm):
        """同 session 两次 run_turn：静态段只组装一次，第二次命中缓存。"""
        calls = _spy_static_build(service)

        await service.run_turn("session-1", Message(role=Role.USER, content="第一轮消息"))
        await service.run_turn("session-1", Message(role=Role.USER, content="第二轮消息"))

        assert len(calls) == 1, f"静态段应只组装 1 次, 实际 {len(calls)} 次"
        assert "session-1" in service._system_prompt_snapshots

        # 两轮 LLM 看到的 system prompt 完全一致（无记忆注入时）
        first, second = mock_llm.chat.call_args_list
        assert _system_content_of(second) == _system_content_of(first)

    @pytest.mark.asyncio()
    async def test_dynamic_memory_appended_after_snapshot_each_turn(
        self, service, mock_llm, mock_memory
    ):
        """动态记忆段每 turn 拼接在缓存快照之后，注入位置与现状一致。"""
        mock_memory.retrieve.return_value = MemoryContext(
            working=[],
            episodic=[{"content": "用户喜欢火锅", "summary": "饮食偏好", "importance": 7}],
            semantic=[],
        )
        calls = _spy_static_build(service)

        await service.run_turn("session-2", Message(role=Role.USER, content="我想吃火锅"))
        await service.run_turn("session-2", Message(role=Role.USER, content="再问一次火锅"))

        assert len(calls) == 1, "记忆每 turn 变化, 但静态段仍应只组装 1 次"
        snapshot = service._system_prompt_snapshots["session-2"]
        for call in mock_llm.chat.call_args_list:
            content = _system_content_of(call)
            # 快照是前缀（静态段），动态记忆段拼在其后
            assert content.startswith(snapshot)
            assert "以下是相关的记忆上下文" in content
            assert "饮食偏好" in content

    @pytest.mark.asyncio()
    async def test_instance_invalidate_forces_rebuild(self, service):
        """invalidate_session_snapshot 后下一轮重新组装静态段。"""
        calls = _spy_static_build(service)

        await service.run_turn("session-3", Message(role=Role.USER, content="第一轮"))
        assert len(calls) == 1

        service.invalidate_session_snapshot("session-3")
        assert "session-3" not in service._system_prompt_snapshots

        await service.run_turn("session-3", Message(role=Role.USER, content="第二轮"))
        assert len(calls) == 2, "失效后应重新组装静态段"
        assert "session-3" in service._system_prompt_snapshots

    @pytest.mark.asyncio()
    async def test_module_level_invalidate_notifies_live_instances(self, service):
        """模块级失效入口（legacy_routes 压缩落点调用）能通知存活实例。"""
        calls = _spy_static_build(service)

        await service.run_turn("session-4", Message(role=Role.USER, content="第一轮"))
        assert "session-4" in service._system_prompt_snapshots

        # legacy_routes._persist_compaction 走的入口
        invalidate_session_snapshot("session-4")
        assert "session-4" not in service._system_prompt_snapshots

        await service.run_turn("session-4", Message(role=Role.USER, content="第二轮"))
        assert len(calls) == 2

    @pytest.mark.asyncio()
    async def test_unknown_session_invalidate_is_noop(self, service):
        """失效不存在的 session 不抛异常。"""
        service.invalidate_session_snapshot("never-seen")
        invalidate_session_snapshot("never-seen")
        assert service._system_prompt_snapshots == {}

    @pytest.mark.asyncio()
    async def test_session_id_none_not_cached(self, service, mock_llm):
        """session_id 为 None 时不缓存，每轮都重新组装（旧路径）。"""
        calls = _spy_static_build(service)

        await service.run_turn(None, Message(role=Role.USER, content="无 session 第一轮"))
        await service.run_turn(None, Message(role=Role.USER, content="无 session 第二轮"))

        assert len(calls) == 2, "session_id=None 不应走缓存"
        assert service._system_prompt_snapshots == {}


# --------------------------------------------------------------------------- #
# 模块级统一写入函数 extract_and_store_memory
# --------------------------------------------------------------------------- #


@pytest.fixture()
def mock_extractor():
    extractor = Mock()
    extractor.extract = AsyncMock(
        return_value=[
            {
                "content": "用户喜欢吃火锅",
                "importance": 7,
                "category": "preference",
                "tags": ["preference"],
            },
            {
                "content": "用户在成都生活",
                "importance": 5,
                "category": "fact",
                "tags": ["location"],
            },
        ]
    )
    return extractor


class TestExtractAndStoreMemory:
    @pytest.mark.asyncio()
    async def test_disabled_returns_zero_without_any_call(self, mock_memory, mock_extractor):
        """enabled=False（autoMemory 关闭）直接返回 0，不提取不写入。"""
        stored = await extract_and_store_memory(
            mock_memory,
            mock_extractor,
            "我想吃火锅",
            "好的, 记住了",
            "session-9",
            enabled=False,
        )
        assert stored == 0
        mock_extractor.extract.assert_not_called()
        mock_memory.store.assert_not_called()

    @pytest.mark.asyncio()
    async def test_none_memory_port_returns_zero(self, mock_extractor):
        """memory_port=None（未装配记忆）直接返回 0。"""
        stored = await extract_and_store_memory(
            None,
            mock_extractor,
            "我想吃火锅",
            "好的, 记住了",
            "session-9",
            enabled=True,
        )
        assert stored == 0
        mock_extractor.extract.assert_not_called()

    @pytest.mark.asyncio()
    async def test_happy_path_returns_count_and_passes_session_id(
        self, mock_memory, mock_extractor
    ):
        """happy path：返回写入条数，store 透传 session_id / importance / tags。"""
        stored = await extract_and_store_memory(
            mock_memory,
            mock_extractor,
            "我想吃火锅, 成都有什么推荐?",
            "好的, 推荐小龙坎和大龙燚",
            "session-9",
            enabled=True,
        )
        assert stored == 2
        mock_extractor.extract.assert_awaited_once_with(
            user_message="我想吃火锅, 成都有什么推荐?",
            assistant_message="好的, 推荐小龙坎和大龙燚",
        )
        assert mock_memory.store.await_count == 2
        first_kwargs = mock_memory.store.call_args_list[0][1]
        assert first_kwargs["content"] == "用户喜欢吃火锅"
        assert first_kwargs["session_id"] == "session-9"
        assert first_kwargs["importance"] == 7
        assert first_kwargs["tags"] == ["preference"]

    @pytest.mark.asyncio()
    async def test_extractor_error_swallowed(self, mock_memory):
        """extractor 抛错：内部吞掉（warning），返回 0，绝不外抛。"""
        extractor = Mock()
        extractor.extract = AsyncMock(side_effect=RuntimeError("LLM down"))
        stored = await extract_and_store_memory(
            mock_memory, extractor, "user text", "assistant text", "s", enabled=True
        )
        assert stored == 0
        mock_memory.store.assert_not_called()

    @pytest.mark.asyncio()
    async def test_store_error_swallowed(self, mock_extractor):
        """store 抛错：内部吞掉（warning），绝不外抛。"""
        memory = Mock(spec=MemoryPort)
        memory.store = AsyncMock(side_effect=RuntimeError("db down"))
        stored = await extract_and_store_memory(
            memory, mock_extractor, "user text", "assistant text", "s", enabled=True
        )
        assert stored == 0
