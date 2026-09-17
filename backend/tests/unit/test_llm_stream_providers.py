"""非 openai provider 流式对话回环测试（r54）。

claude / gemini / ollama 三个真实 provider 的流式路径此前只有 deepseek +
reasoning_effort 一个用例（test_llm_client_reasoning_params.py），openai 之外的
SSE 回环、body 组装（max_tokens / thinking_budget / 无鉴权头）与推理增量
解析都无覆盖。本文件用 respx 模拟各 provider 的 OpenAI 兼容 SSE 端点补齐：

  - claude: chat_stream / chat_stream_events 回环（max_tokens 硬性要求）
  - gemini: thinking_budget 透传进流式 body
  - ollama: 空 api_key 不发 Authorization；reasoning_content → reasoning_delta

全部走 use_proxy=False 直连模式，与既有单测口径一致。
"""

import json

import pytest
import respx
from httpx import Response

from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = [pytest.mark.unit]


def _sse(content: str) -> Response:
    """把若干 content 增量打包成一个 SSE 响应体（| 分隔）。"""
    lines = "".join(
        f'data: {{"choices":[{{"index":0,"delta":{{"content":"{piece}"}}}}]}}\n\n'
        for piece in content.split("|")
    )
    return Response(
        200,
        content=(lines + "data: [DONE]\n\n").encode(),
        headers={"content-type": "text/event-stream"},
    )


def _read_request_body(route_call) -> dict:
    sent = route_call.request
    raw = sent.read() if hasattr(sent, "read") else sent.content
    return json.loads(raw.decode())


# ============================================================================
# claude（OpenAI 兼容网关）—— max_tokens 是 claude 的硬性要求
# ============================================================================


@pytest.mark.asyncio()
async def test_claude_chat_stream_roundtrip_sends_max_tokens():
    with respx.mock(base_url="https://api.anthropic.com", assert_all_called=False) as mock:
        # base_url 带 /v1 时，httpx 把硬编码的 /v1/chat/completions 合并为 /v1/v1/…
        route = mock.post("/v1/v1/chat/completions").mock(return_value=_sse("你好|世界"))
        client = LLMClient(
            LLMConfig(
                provider="claude",
                api_key="sk-ant-test",
                base_url="https://api.anthropic.com/v1",
                model="claude-sonnet-4",
                max_tokens=1024,
                use_proxy=False,
            )
        )
        chunks = [c async for c in client.chat_stream([{"role": "user", "content": "hi"}])]

        assert chunks == ["你好", "世界"]
        body = _read_request_body(route.calls.last)
        assert body["stream"] is True
        assert body["max_tokens"] == 1024
        # 未配置推理参数时不注入，避免被网关拒收
        assert "reasoning_effort" not in body
        assert "thinking_budget" not in body


@pytest.mark.asyncio()
async def test_claude_chat_stream_events_roundtrip():
    with respx.mock(base_url="https://api.anthropic.com", assert_all_called=False) as mock:
        # base_url 带 /v1 时，httpx 把硬编码的 /v1/chat/completions 合并为 /v1/v1/…
        route = mock.post("/v1/v1/chat/completions").mock(return_value=_sse("a|b|c"))
        client = LLMClient(
            LLMConfig(
                provider="claude",
                api_key="sk-ant-test",
                base_url="https://api.anthropic.com/v1",
                model="claude-sonnet-4",
                use_proxy=False,
            )
        )
        events = [
            e
            async for e in client.chat_stream_events(
                [{"role": "user", "content": "hi"}]
            )
        ]

        kinds = [kind for kind, _ in events]
        assert kinds == ["content_delta", "content_delta", "content_delta", "response"]
        # 终值 content = 增量拼接
        assert events[-1][1].content == "abc"
        body = _read_request_body(route.calls.last)
        # L2 真流式契约：附带 include_usage 让网关在末块回传记账数据
        assert body["stream_options"] == {"include_usage": True}
        assert body["max_tokens"] > 0


# ============================================================================
# gemini（OpenAI 兼容模式）—— thinking_budget 透传
# ============================================================================


@pytest.mark.asyncio()
async def test_gemini_chat_stream_forwards_thinking_budget():
    with respx.mock(
        base_url="https://generativelanguage.googleapis.com", assert_all_called=False
    ) as mock:
        route = mock.post("/v1beta/openai/v1/chat/completions").mock(
            return_value=_sse("答|案")
        )
        client = LLMClient(
            LLMConfig(
                provider="gemini",
                api_key="g-key",
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                model="gemini-2.5-flash",
                thinking_budget=2048,
                use_proxy=False,
            )
        )
        chunks = [
            c async for c in client.chat_stream([{"role": "user", "content": "hi"}])
        ]

        assert chunks == ["答", "案"]
        body = _read_request_body(route.calls.last)
        assert body["thinking_budget"] == 2048
        assert "reasoning_effort" not in body


# ============================================================================
# ollama —— 本地无鉴权上游；reasoning 模型的 reasoning_content 解析
# ============================================================================


@pytest.mark.asyncio()
async def test_ollama_chat_stream_roundtrip_without_auth_header():
    with respx.mock(base_url="http://127.0.0.1:11434", assert_all_called=False) as mock:
        # 同上：/v1 后缀 + 客户端硬编码路径 → /v1/v1/…
        route = mock.post("/v1/v1/chat/completions").mock(return_value=_sse("hello|world"))
        client = LLMClient(
            LLMConfig(
                provider="ollama",
                api_key="",
                base_url="http://127.0.0.1:11434/v1",
                model="qwen3:8b",
                use_proxy=False,
            )
        )
        chunks = [
            c async for c in client.chat_stream([{"role": "user", "content": "hi"}])
        ]

        assert chunks == ["hello", "world"]
        # 空 api_key → 不携带 Authorization（本地服务无鉴权）
        assert "authorization" not in {
            k.lower() for k in route.calls.last.request.headers
        }
        body = _read_request_body(route.calls.last)
        assert body["model"] == "qwen3:8b"


@pytest.mark.asyncio()
async def test_ollama_stream_events_reasoning_delta():
    """reasoning 模型（deepseek-r1 等）把思考放 delta.reasoning_content。"""
    lines = (
        'data: {"choices":[{"index":0,"delta":{"reasoning_content":"想"}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"reasoning_content":"一下"}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"答"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    with respx.mock(base_url="http://127.0.0.1:11434", assert_all_called=False) as mock:
        mock.post("/v1/v1/chat/completions").mock(
            return_value=Response(
                200,
                content=lines.encode(),
                headers={"content-type": "text/event-stream"},
            )
        )
        client = LLMClient(
            LLMConfig(
                provider="ollama",
                api_key="",
                base_url="http://127.0.0.1:11434/v1",
                model="deepseek-r1:8b",
                use_proxy=False,
            )
        )
        events = [
            e
            async for e in client.chat_stream_events(
                [{"role": "user", "content": "hi"}]
            )
        ]

        kinds = [kind for kind, _ in events]
        assert kinds == [
            "reasoning_delta",
            "reasoning_delta",
            "content_delta",
            "response",
        ]
        assert events[-1][1].content == "答"
        # 推理文本进 reasoning 字段，不混入 content
        assert events[-1][1].reasoning_content == "想一下"
