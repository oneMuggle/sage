"""
SageAgent 辅助方法测试 (PG1.1 - 覆盖补齐)

`core/agent.py` 覆盖率要从 39% 推到 ≥ 90%,光靠 run_loop / state / streaming
还不够 —— QueryCache、interrupt、execute_tool、get_available_tools、clear_cache
等都是高频入口。本文件为这些"非状态机但很重要"的辅助方法补齐测试。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.exceptions import ToolCallError
from backend.core.legacy import agent as agent_mod
from backend.core.legacy.agent import QueryCache, SageAgent
from backend.core.legacy.llm_client import LLMResponse

pytestmark = pytest.mark.unit


# =============================================================================
# QueryCache
# =============================================================================


def test_query_cache_set_then_get_returns_value():
    """set 后立刻 get,应返回原值。"""
    cache = QueryCache(ttl=300, max_size=10)
    cache.set("s1", "hi", {"message": "world"})
    assert cache.get("s1", "hi") == {"message": "world"}


def test_query_cache_get_returns_none_on_miss():
    """未写入的 key 应返回 None。"""
    cache = QueryCache(ttl=300, max_size=10)
    assert cache.get("nope", "x") is None


def test_query_cache_get_returns_none_for_different_message():
    """同一 session 但不同 message,应视为不同 key。"""
    cache = QueryCache(ttl=300, max_size=10)
    cache.set("s1", "msg-A", {"v": 1})
    assert cache.get("s1", "msg-B") is None


def test_query_cache_expired_entry_is_removed_on_get():
    """TTL=0 的条目在 get 时应被识别为过期并移除。"""
    cache = QueryCache(ttl=0, max_size=10)
    cache.set("s1", "hi", {"v": 1})
    # ttl=0 → 任何条目都视为过期
    assert cache.get("s1", "hi") is None


def test_query_cache_set_overwrites_existing_key():
    """重复 set 同一 key,应只保留最新值。"""
    cache = QueryCache(ttl=300, max_size=10)
    cache.set("s1", "hi", {"v": 1})
    cache.set("s1", "hi", {"v": 2})
    assert cache.get("s1", "hi") == {"v": 2}


def test_query_cache_clear_empties_all_entries():
    """clear() 应清空所有缓存。"""
    cache = QueryCache(ttl=300, max_size=10)
    cache.set("s1", "hi", {"v": 1})
    cache.set("s2", "bye", {"v": 2})
    cache.clear()
    assert cache.get("s1", "hi") is None
    assert cache.get("s2", "bye") is None


def test_query_cache_cleanup_removes_expired_entries():
    """cleanup() 应只移除已过期条目,新鲜条目保留。"""
    cache = QueryCache(ttl=0, max_size=10)
    cache.set("s1", "hi", {"v": 1})  # 立即过期
    removed = cache.cleanup()
    assert removed == 1
    assert cache.get("s1", "hi") is None


def test_query_cache_respects_max_size():
    """超过 max_size 时,最旧条目应被自动驱逐(deque maxlen 行为)。"""
    cache = QueryCache(ttl=300, max_size=2)
    cache.set("s1", "a", {"v": 1})
    cache.set("s2", "b", {"v": 2})
    cache.set("s3", "c", {"v": 3})  # 触发驱逐
    # 最旧的 s1 应被驱逐
    assert cache.get("s1", "a") is None
    assert cache.get("s2", "b") == {"v": 2}
    assert cache.get("s3", "c") == {"v": 3}


# =============================================================================
# SageAgent.interrupt / reset / cache 控制
# =============================================================================


def test_agent_interrupt_and_is_interrupted_round_trip():
    """interrupt() 后 is_interrupted() 应返回 True。"""
    agent = SageAgent()
    assert agent.is_interrupted() is False
    agent.interrupt()
    assert agent.is_interrupted() is True
    agent.reset_interrupt()
    assert agent.is_interrupted() is False


def test_agent_clear_cache_invokes_underlying_cache():
    """clear_cache() 应清空 _cache。"""
    agent = SageAgent()
    agent._cache.set("s", "m", {"x": 1})
    agent.clear_cache()
    assert agent._cache.get("s", "m") is None


def test_agent_cleanup_cache_returns_count():
    """cleanup_cache() 应返回被清理的条目数。"""
    agent = SageAgent()
    # 注入一个 TTL=0 的 cache,然后写入一条
    agent._cache = QueryCache(ttl=0, max_size=10)
    agent._cache.set("s", "m", {"x": 1})
    removed = agent.cleanup_cache()
    assert removed == 1


def test_agent_get_cache_stats_returns_dict_with_size_and_config():
    """get_cache_stats() 应返回包含 size/max_size/ttl 的字典。"""
    agent = SageAgent()
    agent._cache.set("s", "m", {"x": 1})
    stats = agent.get_cache_stats()
    assert stats["size"] == 1
    assert stats["max_size"] == 100
    assert stats["ttl"] == 300


# =============================================================================
# SageAgent.execute_tool
# =============================================================================


def test_execute_tool_returns_tool_result_dict():
    """execute_tool 成功时,应返回 tool.execute(**params).to_dict()。"""
    agent = SageAgent()
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(
        return_value=MagicMock(to_dict=MagicMock(return_value={"out": 42}))
    )
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    result = agent.execute_tool("calculator", {"expression": "1+1"})
    assert result == {"out": 42}
    mock_tool.execute.assert_called_once_with(expression="1+1")


def test_execute_tool_raises_tool_call_error_when_tool_missing():
    """工具不存在时,execute_tool 应抛 ToolCallError。"""
    agent = SageAgent()
    agent.tool_registry.get = MagicMock(return_value=None)

    with pytest.raises(ToolCallError, match="工具不存在"):
        agent.execute_tool("ghost", {})


def test_execute_tool_wraps_unexpected_exception_in_tool_call_error():
    """工具内部抛异常时,execute_tool 应包装为 ToolCallError 并重新抛出。"""
    agent = SageAgent()
    mock_tool = MagicMock()
    mock_tool.execute = MagicMock(side_effect=RuntimeError("boom"))
    agent.tool_registry.get = MagicMock(return_value=mock_tool)

    with pytest.raises(ToolCallError, match="boom"):
        agent.execute_tool("crasher", {})


# =============================================================================
# SageAgent.get_available_tools
# =============================================================================


def test_get_available_tools_delegates_to_tool_registry():
    """get_available_tools() 应包装 tool_registry.get_schemas_for_llm() 为 OpenAI function-calling 格式。"""
    agent = SageAgent()
    # ToolRegistry.get_schemas_for_llm 返回 flat 格式 (name/description/parameters)
    flat_schemas = [
        {"name": "calculator", "description": "do math", "parameters": {}},
    ]
    agent.tool_registry.get_schemas_for_llm = MagicMock(return_value=flat_schemas)

    result = agent.get_available_tools()
    # agent 包装为 OpenAI function-calling 格式
    assert result == [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "do math",
                "parameters": {},
            },
        }
    ]
    agent.tool_registry.get_schemas_for_llm.assert_called_once()


# =============================================================================
# SageAgent.__init__ with explicit LLM config
# =============================================================================


def test_agent_init_with_llm_config_creates_llm_client():
    """传入 llm_config 时,应实例化 LLMClient 并把 llm_config 设为 LLMConfig。"""
    cfg = {
        "provider": "openai",
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "model": "gpt-4",
    }
    agent = SageAgent(llm_config=cfg)
    assert agent.llm_client is not None
    assert agent.llm_config.model == "gpt-4"
    assert agent.llm_config.api_key == "sk-test"


# =============================================================================
# SageAgent.chat: 缓存命中路径(纯单元层、不调 LLM)
# =============================================================================


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_returns_cached_result_when_cache_hit():
    """缓存命中时,chat() 应直接返回缓存,完全不走 LLM 路径。"""
    agent = SageAgent()
    cached = {
        "message": {"id": "cached", "content": "from cache", "role": "assistant"},
        "session": None,
    }
    agent._cache.set("s1", "hi", cached)

    result = await agent.chat("s1", "hi")
    assert result == cached
    # 缓存命中路径不调用 LLM(llm_client=None 也无所谓,因为更早 return)


# =============================================================================
# SageAgent.chat: 未配置 LLM 时的本地模拟响应路径
# =============================================================================


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_returns_simulated_response_when_llm_unset():
    """llm_client is None 时,chat() 应走本地模拟响应分支。"""
    agent = SageAgent()
    # 显式置 None(默认就是 None,但更清楚)
    agent.llm_client = None
    agent.llm_config = None

    # 用一个绝对不存在的 session_id,避免触发 session_repo.get 创建
    result = await agent.chat("never-existed-session", "hi")
    assert result["message"]["role"] == "assistant"
    assert "hi" in result["message"]["content"]
    assert "LLM 未配置" in result["message"]["content"]
    # 本地响应 model 字段为 "local"
    assert result["message"]["model"] == "local"


# =============================================================================
# SageAgent.chat: 配 LLM 时的正常路径
# =============================================================================


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_with_llm_client_returns_llm_response():
    """配置了 LLM 时,chat() 应调用 _call_llm 并返回其内容。"""

    cfg = {
        "provider": "openai",
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "model": "gpt-4",
    }
    agent = SageAgent(llm_config=cfg)
    # 用 AsyncMock 替换真正的 LLM chat 调用
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="mocked LLM reply"))

    result = await agent.chat("s-llm", "user msg")
    assert result["message"]["role"] == "assistant"
    assert result["message"]["content"] == "mocked LLM reply"
    assert result["message"]["model"] == "gpt-4"
    agent.llm_client.chat.assert_awaited_once()


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_with_dynamic_llm_config_restores_original():
    """传入 llm_config 时,chat() 应临时覆盖,结束后恢复。"""

    # 初始化时用 gpt-3.5
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    original_client = agent.llm_client
    original_config = agent.llm_config

    # 替换 LLMClient 构造,使其产生一个 chat() 会抛 LLMError 的实例。
    # 这样无论是初始 client 还是动态配置新建的 client,都被同一个 mock 覆盖。
    class _FlakyClient:
        def __init__(self, config):
            self.config = config
            self.chat = AsyncMock(side_effect=LLMError(LLMErrorType.RATE_LIMITED, "rate limit"))

    with patch.object(agent_mod, "LLMClient", _FlakyClient):
        dynamic_cfg = {
            "provider": "openai",
            "api_key": "k2",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-4-turbo",
        }
        result = await agent.chat("s-dyn", "hi", llm_config=dynamic_cfg)

    # 错误响应
    assert "error" in result
    assert result["error"]["type"] == "rate_limited"

    # 恢复原配置
    assert agent.llm_config is original_config
    assert agent.llm_client is original_client


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_returns_llm_error_response_on_llm_error():
    """LLMError 抛出时,chat() 应返回 error 字段结构化响应,而不是抛异常。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(
        side_effect=LLMError(LLMErrorType.AUTH_FAILED, "bad key", status_code=401)
    )

    result = await agent.chat("s-err", "hi")
    assert result["error"]["type"] == "auth_failed"
    assert result["error"]["message"] == "bad key"
    assert result["error"]["status_code"] == 401
    assert result["message"] is None
    assert result["session"] is None


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_returns_unknown_error_response_on_unexpected_exception():
    """非 LLMError 异常(如 DB 错、编程错)时,chat() 应包装为 UNKNOWN LLMError。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(side_effect=RuntimeError("unexpected"))

    result = await agent.chat("s-boom", "hi")
    assert "error" in result
    assert result["error"]["type"] == "unknown"
    assert "unexpected" in result["error"]["message"]


# =============================================================================
# SageAgent._call_llm & _extract_and_save_memories
# =============================================================================


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_call_llm_returns_llm_response():
    """_call_llm 应构造 system + user 消息并返回 LLM 客户端的响应。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok", model="gpt-3.5-turbo"))

    resp = await agent._call_llm("user msg", memory_context="prior context")
    assert resp.content == "ok"
    # 验证消息体
    call_args = agent.llm_client.chat.await_args
    msgs = call_args.args[0]
    assert msgs[0]["role"] == "system"
    assert "prior context" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"] == "user msg"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_call_llm_works_without_memory_context():
    """memory_context 为空时,system prompt 不应拼接"记忆上下文"段落。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))

    await agent._call_llm("user msg", memory_context="")
    call_args = agent.llm_client.chat.await_args
    msgs = call_args.args[0]
    # 没有记忆上下文时,系统提示不应包含"以下是相关的记忆上下文"
    assert "以下是相关的记忆上下文" not in msgs[0]["content"]


def test_extract_and_save_memories_short_conversation_is_skipped():
    """短对话(双方均 < 100 字符)不应触发情景记忆保存。"""
    agent = SageAgent()
    user_msg = {"content": "hi"}
    asst_msg = {"content": "hello"}
    # 用 mock 验证 memory_manager.remember 没被调用
    agent.memory_manager.remember = MagicMock()
    agent._extract_and_save_memories("s", user_msg, asst_msg)
    agent.memory_manager.remember.assert_not_called()


def test_extract_and_save_memories_long_conversation_is_saved():
    """长对话(任一方 > 100 字符)应触发情景记忆保存。"""
    agent = SageAgent()
    user_msg = {"content": "x" * 150}
    asst_msg = {"content": "y" * 150}
    agent.memory_manager.remember = MagicMock()
    agent._extract_and_save_memories("s", user_msg, asst_msg)
    agent.memory_manager.remember.assert_called_once()
    # 第二个位置参数是 metadata dict
    metadata = agent.memory_manager.remember.call_args.args[1]
    # importance 默认 5
    assert metadata["importance"] == 5


def test_extract_and_save_memories_preference_keyword_boosts_importance():
    """用户消息含偏好关键词(喜欢/偏好/不要/记得/设置/以后)时,importance=7。"""
    agent = SageAgent()
    user_msg = {"content": "我以后" + "x" * 100}  # 长且含偏好词
    asst_msg = {"content": "y" * 150}
    agent.memory_manager.remember = MagicMock()
    agent._extract_and_save_memories("s", user_msg, asst_msg)
    metadata = agent.memory_manager.remember.call_args.args[1]
    assert metadata["importance"] == 7


def test_extract_and_save_memories_swallows_exception():
    """_extract_and_save_memories 自身应吞掉异常,不让 chat() 整个失败。"""
    agent = SageAgent()
    user_msg = {"content": "x" * 150}
    asst_msg = {"content": "y" * 150}
    agent.memory_manager.remember = MagicMock(side_effect=RuntimeError("db down"))
    # 不应抛
    agent._extract_and_save_memories("s", user_msg, asst_msg)


# =============================================================================
# chat() 的持久化失败 + 记忆压缩路径
# =============================================================================


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_continues_when_message_save_fails():
    """message_repo.save 抛错时,chat() 应记录警告但不中断。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))
    agent.message_repo.save = MagicMock(side_effect=RuntimeError("db down"))

    # 不应抛
    result = await agent.chat("s-db-fail", "hi")
    assert result["message"]["content"] == "ok"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_triggers_memory_consolidation_when_over_threshold():
    """工作记忆 token > 3000 时,chat() 应触发 consolidation.consolidate。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))
    # 强制 working.total_tokens 超过阈值
    agent.memory_manager.working.total_tokens = 3001
    agent.consolidation.consolidate = MagicMock()

    await agent.chat("s-mem", "hi")
    agent.consolidation.consolidate.assert_called_once()


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_skips_consolidation_when_under_threshold():
    """工作记忆 token ≤ 3000 时,chat() 不应触发 consolidation。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))
    agent.memory_manager.working.total_tokens = 500
    agent.consolidation.consolidate = MagicMock()

    await agent.chat("s-mem-low", "hi")
    agent.consolidation.consolidate.assert_not_called()


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_updates_session_when_session_exists():
    """session_repo.get 找到 session 时,chat() 应更新 last_message_at 和 message_count。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))
    # 准备一个 mock session
    mock_session = MagicMock()
    mock_session.message_count = 4
    agent.session_repo.get = MagicMock(return_value=mock_session)
    agent.session_repo.update = MagicMock()

    await agent.chat("s-existing", "hi")
    agent.session_repo.update.assert_called_once()
    call_kwargs = agent.session_repo.update.call_args.kwargs
    # message_count 应在原值上加 2(user + assistant)
    assert call_kwargs["message_count"] == 6


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_handles_missing_session_gracefully():
    """session_repo.get 返回 None 时,chat() 不应尝试 update,直接走 result 构造。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))
    agent.session_repo.get = MagicMock(return_value=None)
    agent.session_repo.update = MagicMock()

    result = await agent.chat("s-new", "hi")
    # result.session 应为 None
    assert result["session"] is None
    agent.session_repo.update.assert_not_called()


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_caches_successful_result():
    """成功返回的 result 应被写入 _cache,下次同 query 命中缓存。"""
    agent = SageAgent(
        llm_config={
            "provider": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com/v1",
            "model": "gpt-3.5-turbo",
        }
    )
    agent.llm_client.chat = AsyncMock(return_value=LLMResponse(content="ok"))

    result1 = await agent.chat("s-cache", "hello")
    # 同一 session + 同一 message,缓存命中
    cached = agent._cache.get("s-cache", "hello")
    assert cached is not None
    assert cached["message"]["content"] == result1["message"]["content"]
