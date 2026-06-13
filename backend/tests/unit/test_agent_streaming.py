"""
Agent / LLMClient 流式响应边界测试 (PG1.1 - Task 1.1.3)

注:`backend/core/agent.py` 本身没有 `*_stream` 顶层函数 —— 真正的流式入口是
`LLMClient.chat_stream()`,它以 async generator 形式逐 chunk 返回 LLM 增量内容。
本文件覆盖其关键边界:

1. 多 chunk 拼接:逐个 delta 累加
2. `[DONE]` 哨兵:流正常终止
3. 空 content 字段:不产出空字符串
4. HTTP 错误状态码:抛 RuntimeError(注:Task 11 计划改为 LLMError)
5. 非 JSON 行:被静默跳过,不影响后续 chunk
6. `run_loop` 异步生成器:本身已经是异步流,验证 DONE 后不继续产出事件

这些测试只覆盖流式路径中"易出 bug 的边界",不重复 `test_agent_run_loop.py` 的内容。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.legacy.agent import SageAgent
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse

pytestmark = pytest.mark.unit


# =============================================================================
# 工具:构造一个 SSE 风格的 mock 流式响应
# =============================================================================


def _sse_response(chunks: list, status_code: int = 200):
    """构造一个 mock SSE 响应对象,支持 `aiter_lines()`。

    Args:
        chunks: 每条 SSE 负载。
                - 字典:会被 `json.dumps` 成 `data: {...}\\n\\n`
                - 字符串:按原样写入(用于 `[DONE]` 或损坏行)
        status_code: HTTP 状态码
    """

    lines: list[str] = []
    for c in chunks:
        if isinstance(c, dict):
            lines.append(f"data: {json.dumps(c)}")
        else:
            lines.append(c)
    # SSE 协议:每个事件以空行结束
    body = "\n\n".join(lines) + "\n\n"

    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()

    async def aiter_lines():
        for ln in body.split("\n"):
            # 跳过空行(SSE 事件分隔)
            if ln == "":
                continue
            yield ln

    response.aiter_lines = aiter_lines

    # `client.stream(...)` 是 async context manager
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-3.5-turbo",
        )
    )


# =============================================================================
# LLMClient.chat_stream() 流式边界
# =============================================================================


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_stream_yields_each_delta_in_order():
    """多个 SSE delta 应按顺序逐个 yield 出来。"""
    client = _make_client()
    ctx = _sse_response(
        [
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}]},
            {"choices": [{"delta": {"content": "！"}}]},
        ]
    )

    with pytest.MonkeyPatch.context() as mp:
        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=ctx)
        mp.setattr(client, "_get_client", lambda: mock_http)

        chunks = []
        async for c in client.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(c)

    assert chunks == ["你", "好", "！"]
    # 拼接起来就是完整回答
    assert "".join(chunks) == "你好！"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_stream_terminates_on_done_sentinel():
    """`data: [DONE]` 哨兵出现时,迭代器应停止,不再 yield。

    注:真实 OpenAI SSE 协议下,`[DONE]` 同样带 `data: ` 前缀,例如:
        data: [DONE]
    """
    client = _make_client()
    ctx = _sse_response(
        [
            {"choices": [{"delta": {"content": "片段1"}}]},
            "data: [DONE]",
            # [DONE] 之后如果还有内容,也不应被消费
            {"choices": [{"delta": {"content": "不该出现"}}]},
        ]
    )

    with pytest.MonkeyPatch.context() as mp:
        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=ctx)
        mp.setattr(client, "_get_client", lambda: mock_http)

        chunks = [c async for c in client.chat_stream([{"role": "user", "content": "x"}])]

    assert chunks == ["片段1"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_stream_skips_empty_delta_and_malformed_lines():
    """空 content / 损坏 JSON 行应被静默跳过,不影响后续正常 chunk。"""
    client = _make_client()
    ctx = _sse_response(
        [
            {"choices": [{"delta": {"content": ""}}]},  # 空 content
            "data: not-json-at-all{{{",  # 损坏 JSON
            {"choices": [{"delta": {"role": "assistant"}}]},  # 无 content
            {"choices": [{"delta": {"content": "有效片段"}}]},
        ]
    )

    with pytest.MonkeyPatch.context() as mp:
        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=ctx)
        mp.setattr(client, "_get_client", lambda: mock_http)

        chunks = [c async for c in client.chat_stream([{"role": "user", "content": "x"}])]

    assert chunks == ["有效片段"]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_chat_stream_raises_runtime_error_on_http_error():
    """HTTP 错误状态码应抛 RuntimeError(注:后续 Task 11 将统一为 LLMError 分类)。"""
    client = _make_client()
    ctx = _sse_response([], status_code=500)
    # 覆写 raise_for_status 抛错
    ctx.__aenter__.return_value.raise_for_status = MagicMock(side_effect=Exception("HTTP 500"))

    with pytest.MonkeyPatch.context() as mp:
        mock_http = MagicMock()
        mock_http.stream = MagicMock(return_value=ctx)
        mp.setattr(client, "_get_client", lambda: mock_http)

        async def _consume():
            async for _ in client.chat_stream([{"role": "user", "content": "x"}]):
                pass

        with pytest.raises(RuntimeError, match="LLM 流式请求"):
            await _consume()


# =============================================================================
# SageAgent.run_loop() 作为异步生成器的流式契约
# =============================================================================
# 之所以把这部分放在 streaming 测试里,是因为 run_loop 是 NDJSON 流式接口的
# 唯一事件源。它本身已是 async generator,这里只补充"流式契约"相关的几条:
# 1. DONE / FAILED 之后迭代器应立即终止
# 2. 多次迭代之间不残留状态


def _mock_llm_no_tool(content: str = "ok") -> MagicMock:
    """构造一个永远返回纯文本的 LLM mock。"""
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=LLMResponse(content=content, tool_calls=[]))
    return mock_client


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_run_loop_terminates_immediately_after_done_event():
    """DONE 事件之后,async for 应立即停止(不再有 THINKING 之类的后续事件)。"""
    agent = SageAgent()
    agent.llm_client = _mock_llm_no_tool("final answer")

    events = []
    async for evt in agent.run_loop([{"role": "user", "content": "x"}]):
        events.append(evt)

    # 最后一个必须是 DONE
    assert events[-1].state.value == "done"
    # DONE 之后不应再有 THINKING
    done_idx = next(i for i, e in enumerate(events) if e.state.value == "done")
    assert "thinking" not in [e.state.value for e in events[done_idx + 1 :]]


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
async def test_run_loop_reusable_across_iterations():
    """同一个 agent 实例可以连续多次运行 run_loop,无残留状态。

    注:run_loop 会把 assistant 消息追加进传入的 messages 列表(就地修改),
    所以这里验证的是:两次调用之间不会出现"事件流被污染"或"LLM 调用计数错乱"。
    """
    agent = SageAgent()
    agent.llm_client = _mock_llm_no_tool("reply")

    # 第一次
    msgs1 = [{"role": "user", "content": "first"}]
    async for _ in agent.run_loop(msgs1):
        pass

    # 第二次(不同 messages)
    msgs2 = [{"role": "user", "content": "second"}]
    events2 = []
    async for evt in agent.run_loop(msgs2):
        events2.append(evt)

    # 第二次的最终事件仍是 DONE,内容是 LLM mock 返回的 "reply"
    assert events2[-1].state.value == "done"
    assert events2[-1].content == "reply"
    # LLM 被调用了 2 次(每次 run_loop 一次)
    assert agent.llm_client.chat.await_count == 2
    # messages2 末尾被追加了 assistant 消息(就地修改的预期行为)
    assert msgs2[-1]["role"] == "assistant"
    assert msgs2[-1]["content"] == "reply"
