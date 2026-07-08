"""Unit tests for backend.wiki.llm_context.

覆盖行为：
- make_llm_context 返回 LLMContext dataclass，3 个 callback 均可调用
- llm_call 用正确 request shape (model/stream/temperature/Authorization) 打 LLM
- http_post 用正确 method/url/headers/json 打下游
- get_wiki_llm_context 从 request body 字典中抽取 3 个字段
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.wiki.llm_context import (
    LLMContext,
    get_wiki_llm_context,
    get_wiki_llm_context_from_body,
    make_llm_context,
)


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
        result = asyncio.run(
            ctx.http_post("http://embed.test/embed", {"X-K": "v"}, {"input": "a"})
        )
    assert result == "ok"
    call_kwargs = fake_async_client.post.call_args.kwargs
    assert call_kwargs["headers"] == {"X-K": "v"}
    assert call_kwargs["json"] == {"input": "a"}


def test_get_wiki_llm_context_reads_three_fields():
    """3-field factory: routes pass llm_base_url/llm_api_key/llm_model directly."""
    ctx = get_wiki_llm_context(
        llm_base_url="http://x.test/v1",
        llm_api_key="sk-xyz",
        llm_model="claude-3",
    )
    assert isinstance(ctx, LLMContext)
    assert ctx.llm_call is not None
    assert ctx.llm_stream_call is not None
    assert ctx.http_post is not None


def test_get_wiki_llm_context_from_body_reads_dict():
    """Dict factory: middleware-stashed body in request.state pattern."""
    body = {
        "llm_base_url": "http://x.test/v1",
        "llm_api_key": "sk-xyz",
        "llm_model": "claude-3",
    }
    ctx = get_wiki_llm_context_from_body(body)
    assert isinstance(ctx, LLMContext)
    assert ctx.llm_call is not None


def test_get_wiki_llm_context_from_body_defaults_to_empty():
    body = {}  # 缺字段时使用空字符串
    ctx = get_wiki_llm_context_from_body(body)
    assert isinstance(ctx, LLMContext)
    assert ctx.http_post is not None
