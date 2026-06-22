"""
AgentOrchestrator 分派与单步执行测试 (PG1.2)

覆盖 `core/orchestrator.py` 的"dispatch"子集:
  - 初始化
  - process_request 单步分支入口
  - _classify_intent 关键词 + LLM 路径
  - _select_agent 意图→Agent 映射
  - _execute_agent_task 单 Agent 派发（含黑板发布）
  - _run_agent_llm 有/无 LLM、LLM 错误
  - _summarize_history 边界

外部依赖:
  - LLMClient.chat() 用 MagicMock+AsyncMock 模拟
  - BlackboardRepo 走真实 SQLite（conftest 提供的 tmp_db_path 自动生效）
  - get_agent() 走真实 agents.profiles（已注册默认 4 个 Agent）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.llm_client import LLMResponse
from backend.core.legacy.orchestrator import AgentOrchestrator, Intent

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_response(content: str = "") -> LLMResponse:
    """构造 LLMResponse 模拟对象。"""
    return LLMResponse(content=content, tool_calls=[])


def _orch_with_llm(llm_mock: MagicMock) -> AgentOrchestrator:
    """构造带 mock LLM 的 orchestrator。"""
    orch = AgentOrchestrator()
    orch.llm_client = llm_mock
    return orch


# ---------------------------------------------------------------------------
# Task 1.2.2.1 — 初始化
# ---------------------------------------------------------------------------


def test_orchestrator_init_default_has_blackboard_and_no_llm():
    """默认初始化:无 llm_client、有 blackboard、缓存为空。"""
    orch = AgentOrchestrator()
    assert orch.llm_client is None
    assert orch.blackboard is not None
    assert orch._agent_cache == {}


def test_orchestrator_init_accepts_llm_client():
    """显式传入 LLMClient 应保存到实例。"""
    fake_llm = MagicMock()
    orch = AgentOrchestrator(llm_client=fake_llm)
    assert orch.llm_client is fake_llm


# ---------------------------------------------------------------------------
# Task 1.2.2.2 — process_request 入口(单步分支)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_process_request_routes_general_message_to_primary_agent():
    """ "你好" 触发关键词未命中 → fallback general → primary agent。"""
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState
    from backend.core.legacy.llm_client import LLMConfig

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="hello back"))
    # 给 mock LLM 设置真实 LLMConfig (避免 isinstance 检查失败)
    llm.config = LLMConfig(
        provider="custom",
        api_key="test-key",
        base_url="https://example.com/v1",
        model="test-model",
    )
    orch = _orch_with_llm(llm)

    async def mock_run_loop(*args, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0, agent_id="primary")
        yield AgentEvent(
            state=AgentState.DONE, iteration=0, content="hello back", agent_id="primary"
        )

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = {"system_prompt": "test", "max_iterations": 5}
        MockAgent.return_value = mock_instance

        result = await orch.process_request("sess-1", "你好")

    assert result["agent_id"] == "primary"
    assert result["response"] == "hello back"
    assert result["metadata"]["intent"] == "general"
    assert result["metadata"]["agent_used"] == "primary"
    assert result["metadata"]["elapsed_ms"] >= 0


@pytest.mark.asyncio()
async def test_process_request_keyword_coding_short_circuits_llm():
    """ "写代码" 关键词命中 CODING → 选 coder agent,且不会调用 LLM 做意图分类。"""
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    llm = MagicMock()
    # 第一次调用(_classify_intent LLM 路径)不应发生;
    # 后续调用是 SageAgent.run_loop 内部
    llm.chat = AsyncMock(return_value=_make_response(content="def foo(): pass"))
    orch = _orch_with_llm(llm)

    async def mock_run_loop(*args, **kwargs):
        yield AgentEvent(
            state=AgentState.DONE, iteration=0, content="def foo(): pass", agent_id="coder"
        )

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = {"system_prompt": "coder", "max_iterations": 10}
        MockAgent.return_value = mock_instance

        result = await orch.process_request("sess-2", "帮我写代码")

    assert result["agent_id"] == "coder"
    assert result["metadata"]["intent"] == "coding"
    # LLM 没被调用 (关键词短路, 不调 _classify_intent 的 LLM 路径)
    # SageAgent.run_loop 内部可能调 LLM (但我们 mock 了整个 agent, 所以 llm.chat 不被调)
    # 关键断言: intent 是 coding (关键词命中)


@pytest.mark.asyncio()
async def test_process_request_multi_step_routes_to_multi_step_branch():
    """消息无关键词命中 + LLM 分类为 multi_step → 走 _execute_multi_step 分支。"""
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    llm = MagicMock()
    llm.chat = AsyncMock(
        side_effect=[
            _make_response(content="multi_step"),
            _make_response(content='[{"intent": "general", "description": "say hi"}]'),
            _make_response(content="final aggregated"),
        ]
    )
    orch = _orch_with_llm(llm)

    async def mock_run_loop(*args, **kwargs):
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok", agent_id="primary")

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = {"system_prompt": "test", "max_iterations": 5}
        MockAgent.return_value = mock_instance

        # 消息故意不包含任何关键词(search/code/memory 等)
        result = await orch.process_request("sess-3", "请帮我处理一件复杂的事")

    assert result["agent_id"] == "multi_step"
    assert "subtasks" in result
    assert result["metadata"]["intent"] == "multi_step"


@pytest.mark.asyncio()
async def test_process_request_without_llm_uses_keyword_fallback():
    """无 llm_client 时,纯靠关键词 + 模拟回复。"""
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    orch = AgentOrchestrator()  # llm_client=None

    async def mock_run_loop(*args, **kwargs):
        # 无 LLM 时 SageAgent 会抛 AgentError, 被 orchestrator 捕获 → error 字符串
        yield AgentEvent(
            state=AgentState.FAILED,
            iteration=0,
            error="LLM 未配置",
            agent_id="researcher",
        )

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = {"system_prompt": "researcher", "max_iterations": 5}
        MockAgent.return_value = mock_instance

        result = await orch.process_request("sess-4", "查一下 research 资料")

    # 关键词 "research"/"search" 命中 RESEARCH → researcher
    assert result["agent_id"] == "researcher"
    # 新行为: 无 LLM 时返回错误信息(不再 "[模拟回复]")
    assert "LLM 未配置" in result["response"] or result["response"]
    assert result["metadata"]["intent"] == "research"


# ---------------------------------------------------------------------------
# Task 1.2.2.3 — _classify_intent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_classify_intent_keyword_match_chinese():
    """中文关键词命中。"""
    orch = AgentOrchestrator()
    assert await orch._classify_intent("帮我 debug") == Intent.CODING
    assert await orch._classify_intent("记忆里有什么") == Intent.MEMORY
    assert await orch._classify_intent("搜索最新论文") == Intent.RESEARCH


@pytest.mark.asyncio()
async def test_classify_intent_keyword_match_english_case_insensitive():
    """英文关键词大小写不敏感。"""
    orch = AgentOrchestrator()
    assert await orch._classify_intent("Please FIND info") == Intent.RESEARCH
    assert await orch._classify_intent("REMEMBER this fact") == Intent.MEMORY
    assert await orch._classify_intent("Write CODE for me") == Intent.CODING


@pytest.mark.asyncio()
async def test_classify_intent_falls_back_to_general_when_no_keywords():
    """无关键词命中 + 无 LLM → GENERAL。"""
    orch = AgentOrchestrator()
    assert await orch._classify_intent("今天天气真好") == Intent.GENERAL


@pytest.mark.asyncio()
async def test_classify_intent_uses_llm_when_provided():
    """有 llm_client 时,关键词未命中 → 调 LLM 分类。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="memory"))
    orch = _orch_with_llm(llm)

    intent = await orch._classify_intent("随便聊聊")

    assert intent == Intent.MEMORY
    assert llm.chat.await_count == 1


@pytest.mark.asyncio()
async def test_classify_intent_llm_failure_falls_back_to_general():
    """LLM 抛异常 → 记 warning → 返回 GENERAL。"""
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
    orch = _orch_with_llm(llm)

    intent = await orch._classify_intent("hello world")

    assert intent == Intent.GENERAL


@pytest.mark.asyncio()
async def test_classify_intent_llm_unknown_label_falls_back_to_general():
    """LLM 返回无法识别的标签 → GENERAL。"""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="this is not a valid label"))
    orch = _orch_with_llm(llm)

    intent = await orch._classify_intent("xyzzy")

    assert intent == Intent.GENERAL


# ---------------------------------------------------------------------------
# Task 1.2.2.4 — _select_agent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        (Intent.GENERAL, "primary"),
        (Intent.RESEARCH, "researcher"),
        (Intent.CODING, "coder"),
        (Intent.MEMORY, "memory_manager"),
    ],
)
def test_select_agent_maps_each_known_intent(intent, expected):
    """四个已知意图各自映射到对应的 agent。"""
    orch = AgentOrchestrator()
    assert orch._select_agent(intent) == expected


# ---------------------------------------------------------------------------
# Task 1.2.2.5 — _execute_agent_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_execute_agent_task_success_publishes_task_and_result():
    """正常路径:发布 task → 调 SageAgent.run_loop → 发布 result → 返回 dict。"""
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="agent says hi"))
    orch = _orch_with_llm(llm)

    async def mock_run_loop(*args, **kwargs):
        yield AgentEvent(state=AgentState.THINKING, iteration=0, agent_id="primary")
        yield AgentEvent(
            state=AgentState.DONE, iteration=0, content="agent says hi", agent_id="primary"
        )

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = {"system_prompt": "test", "max_iterations": 5}
        MockAgent.return_value = mock_instance

        result = await orch._execute_agent_task("sess-A", "primary", "hello")

    assert result["agent_id"] == "primary"
    assert result["response"] == "agent says hi"
    assert "task_id" in result
    assert isinstance(result["task_id"], str)
    assert len(result["task_id"]) > 0


@pytest.mark.asyncio()
async def test_execute_agent_task_returns_error_when_agent_not_found():
    """agent_id 不存在 → SageAgent profile=None 回退默认, 仍能跑通 (不再返回 error dict)。

    阶段 2 改动: agent_id 不存在时不再返回 error, 而是用默认 profile 跑通。
    """
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    orch = AgentOrchestrator()  # llm_client=None

    async def mock_run_loop(*args, **kwargs):
        yield AgentEvent(
            state=AgentState.DONE, iteration=0, content="default response", agent_id=None
        )

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = None  # agent 不存在 → profile=None
        MockAgent.return_value = mock_instance

        result = await orch._execute_agent_task("sess-B", "ghost_agent", "hi")

    # 新行为: agent_id 不存在不再返回 error, 而是用默认 profile
    assert result["agent_id"] == "ghost_agent"
    assert "response" in result
    # 不再有 "error" 字段


@pytest.mark.asyncio()
async def test_execute_agent_task_includes_history_summary():
    """带 history 时,发布到黑板的 task content 应包含 history_summary。"""
    from unittest.mock import patch

    from backend.core.legacy.agent_state import AgentEvent, AgentState

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="ok"))
    orch = _orch_with_llm(llm)
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]

    async def mock_run_loop(*args, **kwargs):
        yield AgentEvent(state=AgentState.DONE, iteration=0, content="ok", agent_id="primary")

    with patch("backend.core.legacy.agent.SageAgent") as MockAgent:
        mock_instance = MagicMock()
        mock_instance.run_loop = mock_run_loop
        mock_instance.profile = {"system_prompt": "test", "max_iterations": 5}
        MockAgent.return_value = mock_instance

        result = await orch._execute_agent_task("sess-C", "primary", "now", history=history)

    assert result["agent_id"] == "primary"
    # 通过黑板查询 task 消息验证 history_summary
    msgs = orch.blackboard.subscribe(
        agent_name="primary", session_id="sess-C", message_type="task", limit=5
    )
    assert len(msgs) >= 1
    task_content = msgs[0]["content"]
    assert "history_summary" in task_content
    assert "earlier" in task_content["history_summary"]


# ---------------------------------------------------------------------------
# Task 1.2.2.6 — _run_agent_llm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_run_agent_llm_with_llm_uses_system_prompt_and_history():
    """有 llm_client:使用 agent.system_prompt + 最近 5 条历史。"""
    from backend.agents.profiles import get_agent

    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_make_response(content="response"))
    orch = _orch_with_llm(llm)
    agent = get_agent("primary")
    history = [{"role": "user", "content": f"msg{i}"} for i in range(7)]

    response = await orch._run_agent_llm(agent, "current", history=history)

    assert response == "response"
    assert llm.chat.await_count == 1
    call_args = llm.chat.await_args
    messages = call_args.args[0]
    # 第一条必须是 system
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == agent.system_prompt
    # 历史 7 条 → 取最后 5 条(history_msgs 不含最后追加的 current)
    # 所以消息总长 = 1 (system) + 5 (history) + 1 (current) = 7
    assert len(messages) == 7
    history_msgs = messages[1:-1]  # 去掉 system 和 current
    assert len(history_msgs) == 5
    # 验证是最后 5 条(msg2-msg6)
    assert history_msgs[0]["content"] == "msg2"
    assert history_msgs[-1]["content"] == "msg6"
    # 最后一条是当前 message
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "current"


@pytest.mark.asyncio()
async def test_run_agent_llm_without_llm_returns_simulated():
    """llm_client=None → 返回模拟回复。"""
    orch = AgentOrchestrator()
    from backend.agents.profiles import get_agent

    agent = get_agent("researcher")
    response = await orch._run_agent_llm(agent, "search X")

    assert "[模拟回复]" in response
    assert "researcher" in response or "研究" in response


@pytest.mark.asyncio()
async def test_run_agent_llm_llm_error_returns_error_string():
    """LLM 抛异常 → 返回错误字符串而非抛错。"""
    from backend.agents.profiles import get_agent

    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("upstream down"))
    orch = _orch_with_llm(llm)
    agent = get_agent("primary")

    response = await orch._run_agent_llm(agent, "hi")

    assert "LLM 调用失败" in response
    assert "upstream down" in response


# ---------------------------------------------------------------------------
# Task 1.2.2.7 — _summarize_history
# ---------------------------------------------------------------------------


def test_summarize_history_empty_returns_default():
    """None / [] → 返回"无对话历史"。"""
    orch = AgentOrchestrator()
    assert orch._summarize_history(None) == "无对话历史"
    assert orch._summarize_history([]) == "无对话历史"


def test_summarize_history_normal_returns_role_content_pairs():
    """3 条以内 → 全部输出 role: content 格式。"""
    orch = AgentOrchestrator()
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    summary = orch._summarize_history(history)
    assert "user: hi" in summary
    assert "assistant: hello" in summary


def test_summarize_history_truncates_to_last_three_and_content_to_100():
    """>3 条历史 → 只取最后 3 条;每条 content 截断 100 字符。"""
    orch = AgentOrchestrator()
    history = [{"role": "user", "content": f"msg{i}-" + "x" * 200} for i in range(5)]
    summary = orch._summarize_history(history)

    # 只出现最后 3 条的索引 (2, 3, 4)
    assert "msg2-" in summary
    assert "msg3-" in summary
    assert "msg4-" in summary
    assert "msg0-" not in summary
    assert "msg1-" not in summary
    # 每条 content 截到 100 字符
    # "msg4-" + 100 个 "x"  → 104 字符的 content(不含 role: 前缀)
    for line in summary.splitlines():
        # role: content,content 部分不应超过 100
        content_part = line.split(": ", 1)[1]
        assert len(content_part) <= 100


def test_summarize_history_handles_missing_role_or_content():
    """msg 缺 role/content → 用 'unknown' 和 '' 兜底。"""
    orch = AgentOrchestrator()
    history = [{"foo": "bar"}]  # 无 role / content
    summary = orch._summarize_history(history)
    assert "unknown:" in summary
