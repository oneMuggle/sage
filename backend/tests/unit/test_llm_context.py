"""Unit tests for backend.wiki.llm_context.

覆盖行为：
- make_llm_context 返回 LLMContext dataclass，3 个 callback 均可调用
- llm_call 用正确 request shape (model/stream/temperature/Authorization) 打 LLM
- http_post 用正确 method/url/headers/json 打下游
- llm_stream_call 解析 SSE chunks 累加 content 字段
- llm_stream_call 静默跳过非 JSON 行
"""

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

from backend.wiki.llm_context import LLMContext, make_llm_context


def _sse_response(lines: List[str]):
    """构造一个 mock SSE 响应对象,支持 `aiter_lines()`。

    `lines` 是每个 `aiter_lines()` yield 的单行字符串(不含换行符)。
    `client.stream(...)` 返回的 async context manager 的 __aenter__
    返回本对象。
    """

    async def aiter_lines():
        for ln in lines:
            yield ln

    response = MagicMock()
    response.aiter_lines = aiter_lines
    response.raise_for_status = MagicMock()
    return response


def test_make_llm_context_returns_dataclass():
    ctx = make_llm_context("http://api.test", "sk-test", "gpt-4")
    assert isinstance(ctx, LLMContext)
    assert callable(ctx.llm_call)
    assert callable(ctx.llm_stream_call)
    assert callable(ctx.http_post)


def test_llm_call_uses_correct_request_shape():
    ctx = make_llm_context("http://api.test/v1", "sk-abc", "gpt-4o-mini")
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "hi"}}]}
    fake_response.raise_for_status = MagicMock()
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_async_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)
    fake_async_client.post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient", return_value=fake_async_client):
        result = asyncio.run(ctx.llm_call([{"role": "user", "content": "x"}], 0.7))
    assert result == "hi"
    call_kwargs = fake_async_client.post.call_args.kwargs
    assert call_kwargs["json"]["model"] == "gpt-4o-mini"
    assert call_kwargs["json"]["stream"] is False
    assert call_kwargs["json"]["temperature"] == 0.7
    assert "Authorization" in call_kwargs["headers"]
    # URL 末尾追加 /chat/completions
    assert call_kwargs["json"]["messages"] == [{"role": "user", "content": "x"}]
    assert fake_async_client.post.call_args.args[0].endswith("/chat/completions")


def test_http_post_returns_text():
    ctx = make_llm_context("http://api.test", "sk-test", "gpt-4")
    fake_response = MagicMock()
    fake_response.text = "ok"
    fake_response.raise_for_status = MagicMock()
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_async_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)
    fake_async_client.post = AsyncMock(return_value=fake_response)
    with patch("httpx.AsyncClient", return_value=fake_async_client):
        result = asyncio.run(ctx.http_post("http://embed.test/embed", {"X-K": "v"}, {"input": "a"}))
    assert result == "ok"
    call_kwargs = fake_async_client.post.call_args.kwargs
    assert call_kwargs["headers"] == {"X-K": "v"}
    assert call_kwargs["json"] == {"input": "a"}


def test_llm_stream_call_parses_sse_chunks():
    """happy path: SSE 'data: {...}' lines parsed, deltas yielded, [DONE] 终止."""
    ctx = make_llm_context("http://api.test/v1", "sk-abc", "gpt-4o-mini")
    response = _sse_response(
        [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            "",
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            "",
            "data: [DONE]",
            "",
        ]
    )
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=response)
    stream_ctx.__aexit__ = AsyncMock(return_value=None)
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_async_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)
    fake_async_client.stream = MagicMock(return_value=stream_ctx)
    with patch("httpx.AsyncClient", return_value=fake_async_client):

        async def collect():
            return [d async for d in ctx.llm_stream_call([{"role": "user", "content": "x"}], 0.7)]

        chunks = asyncio.run(collect())
    assert chunks == ["Hello", " world"]
    # 验证 request shape: stream=True + temperature=0.7 + model + Authorization
    stream_kwargs = fake_async_client.stream.call_args.kwargs
    assert stream_kwargs["json"]["stream"] is True
    assert stream_kwargs["json"]["temperature"] == 0.7
    assert stream_kwargs["json"]["model"] == "gpt-4o-mini"
    assert "Authorization" in stream_kwargs["headers"]
    # 方法 + URL
    assert fake_async_client.stream.call_args.args[0] == "POST"
    assert fake_async_client.stream.call_args.args[1].endswith("/chat/completions")


def test_llm_stream_call_skips_malformed_lines():
    """坏 JSON 行被静默跳过,有效 chunk 仍正常 yield."""
    ctx = make_llm_context("http://api.test/v1", "sk-abc", "gpt-4o-mini")
    response = _sse_response(
        [
            "data: not-valid-json",
            "",
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            "",
        ]
    )
    stream_ctx = MagicMock()
    stream_ctx.__aenter__ = AsyncMock(return_value=response)
    stream_ctx.__aexit__ = AsyncMock(return_value=None)
    fake_async_client = MagicMock()
    fake_async_client.__aenter__ = AsyncMock(return_value=fake_async_client)
    fake_async_client.__aexit__ = AsyncMock(return_value=None)
    fake_async_client.stream = MagicMock(return_value=stream_ctx)
    with patch("httpx.AsyncClient", return_value=fake_async_client):

        async def collect():
            return [d async for d in ctx.llm_stream_call([{"role": "user", "content": "x"}], 0.7)]

        chunks = asyncio.run(collect())
    assert chunks == ["ok"]
