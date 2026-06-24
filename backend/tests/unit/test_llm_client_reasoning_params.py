"""
LLMClient reasoning_effort / thinking_budget 透传测试（PR-7a）。

覆盖：
  - LLMConfig 新字段默认值（向后兼容）
  - chat() 把 reasoning_effort / thinking_budget 加到请求体
  - chat() 不传时（None）不加 key,避免污染老 LLM
  - chat_stream() 同样把这两个 key 加到流式请求体
  - 字段类型校验（reasoning_effort 是字符串,thinking_budget 是整数）
"""

import json

import pytest
import respx
from httpx import Response

from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


def _make_config(**overrides) -> LLMConfig:
    defaults = {
        "provider": "gemini",
        "api_key": "test-key",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.5-flash",
        "use_proxy": False,  # 测试模式：直连上游，方便 mock
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


# ============================================================================
# LLMConfig 字段默认值（向后兼容）
# ============================================================================


def test_llmconfig_reasoning_params_default_to_none():
    """不传新字段时,两个推理参数都默认 None — 老调用方零影响。"""
    cfg = LLMConfig()
    assert cfg.reasoning_effort is None
    assert cfg.thinking_budget is None


def test_llmconfig_accepts_explicit_reasoning_params():
    """显式传新字段时,值被正确保留。"""
    cfg = LLMConfig(reasoning_effort="high", thinking_budget=2048)
    assert cfg.reasoning_effort == "high"
    assert cfg.thinking_budget == 2048


# ============================================================================
# chat() 请求体透传
# ============================================================================


def _read_request_body(route_call) -> dict:
    """从 respx 的最后一次 call 里拿出请求 body 转 dict。"""
    sent = route_call.request
    raw = sent.read() if hasattr(sent, "read") else sent.content
    return json.loads(raw.decode())


@pytest.mark.asyncio()
async def test_chat_forwards_reasoning_effort_to_request_body():
    """reasoning_effort 非 None 时,出现在 POST /chat/completions 的 body 里。"""
    with respx.mock(
        base_url="https://generativelanguage.googleapis.com", assert_all_called=False
    ) as mock:
        route = mock.post("/v1beta/openai/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "x",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        client = LLMClient(_make_config(reasoning_effort="medium"))
        await client.chat([{"role": "user", "content": "hi"}])
        body = _read_request_body(route.calls.last)
        assert body["reasoning_effort"] == "medium"
        # thinking_budget 没设,不应该出现在 body
        assert "thinking_budget" not in body


@pytest.mark.asyncio()
async def test_chat_forwards_thinking_budget_to_request_body():
    """thinking_budget 非 None 时,出现在 POST /chat/completions 的 body 里。"""
    with respx.mock(
        base_url="https://generativelanguage.googleapis.com", assert_all_called=False
    ) as mock:
        route = mock.post("/v1beta/openai/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "x",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        client = LLMClient(_make_config(thinking_budget=4096))
        await client.chat([{"role": "user", "content": "hi"}])
        body = _read_request_body(route.calls.last)
        assert body["thinking_budget"] == 4096
        assert "reasoning_effort" not in body


@pytest.mark.asyncio()
async def test_chat_does_not_inject_reasoning_params_when_none():
    """两个推理参数都是 None 时,body 里不应该出现这两个 key,避免污染老 LLM。"""
    with respx.mock(
        base_url="https://generativelanguage.googleapis.com", assert_all_called=False
    ) as mock:
        route = mock.post("/v1beta/openai/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "x",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        client = LLMClient(_make_config())  # 不传任何推理参数
        await client.chat([{"role": "user", "content": "hi"}])
        body = _read_request_body(route.calls.last)
        assert "reasoning_effort" not in body
        assert "thinking_budget" not in body


@pytest.mark.asyncio()
async def test_chat_can_send_both_params_simultaneously():
    """两个参数可以同时存在 — 由上游 provider 决定接受哪个。"""
    with respx.mock(
        base_url="https://generativelanguage.googleapis.com", assert_all_called=False
    ) as mock:
        route = mock.post("/v1beta/openai/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "x",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        client = LLMClient(_make_config(reasoning_effort="high", thinking_budget=-1))
        await client.chat([{"role": "user", "content": "hi"}])
        body = _read_request_body(route.calls.last)
        assert body["reasoning_effort"] == "high"
        assert body["thinking_budget"] == -1


# ============================================================================
# chat_stream() 请求体透传
# ============================================================================


@pytest.mark.asyncio()
async def test_chat_stream_forwards_reasoning_params_to_request_body():
    """chat_stream() 同样把 reasoning_effort/thinking_budget 写进 body。"""
    with respx.mock(base_url="https://api.deepseek.com", assert_all_called=False) as mock:
        route = mock.post("/v1/v1/chat/completions").mock(
            return_value=Response(
                200,
                content=b'data: {"id":"x","choices":[{"index":0,"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
                headers={"content-type": "text/event-stream"},
            )
        )
        client = LLMClient(
            LLMConfig(
                provider="deepseek",
                api_key="k",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-reasoner",
                reasoning_effort="high",
                use_proxy=False,
            )
        )
        async for _ in client.chat_stream([{"role": "user", "content": "hi"}]):
            pass
        body = _read_request_body(route.calls.last)
        assert body["stream"] is True
        assert body["reasoning_effort"] == "high"
        assert "thinking_budget" not in body
