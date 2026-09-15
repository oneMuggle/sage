# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""D-1 (round5 批次 D): fallback model 降级测试。

主模型可重试类错误（429）重试耗尽后，配了 fallback_model 的 client 应
以 fallback model 重发一轮并成功；未配置时照旧抛 LLMError；fallback
每实例至多触发一次。
"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


def _rate_limited_response():
    resp = AsyncMock()
    resp.status_code = 429
    resp.text = "rate limited"
    resp.headers = {}
    resp.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("429", request=AsyncMock(), response=resp)
    )
    return resp


def _ok_response(model: str):
    resp = AsyncMock()
    resp.status_code = 200
    resp.raise_for_status = Mock()
    resp.json = Mock(
        return_value={
            "model": model,
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }
    )
    return resp


def _make_client(fallback_model=None) -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-4o",
            fallback_model=fallback_model,
        )
    )


@pytest.mark.asyncio()
async def test_no_fallback_raises_after_retries_exhausted(client=None):
    client = _make_client()
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=_rate_limited_response())
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])

    assert exc_info.value.type == LLMErrorType.RATE_LIMITED
    # 默认 3 次尝试,全部打主模型
    assert mock_http.post.await_count == 3
    assert mock_http.post.await_args_list[0][1]["json"]["model"] == "gpt-4o"


@pytest.mark.asyncio()
async def test_fallback_model_takes_over_after_retry_exhaustion():
    client = _make_client(fallback_model="gpt-4o-mini")
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        # 前 3 次主模型 429,之后 fallback 模型成功
        mock_http.post = AsyncMock(
            side_effect=[_rate_limited_response(), _rate_limited_response(),
                         _rate_limited_response(), _ok_response("gpt-4o-mini")]
        )
        mock_get_client.return_value = mock_http

        response = await client.chat([{"role": "user", "content": "hi"}])

    assert response.content == "ok"
    assert mock_http.post.await_count == 4
    assert mock_http.post.await_args_list[3][1]["json"]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio()
async def test_fallback_triggers_only_once():
    client = _make_client(fallback_model="gpt-4o-mini")
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        # fallback 也一直 429 → 耗尽后必须抛错,而不是无限降级
        mock_http.post = AsyncMock(return_value=_rate_limited_response())
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "hi"}])

    # 主模型 3 次 + fallback 3 次 = 6
    assert mock_http.post.await_count == 6


@pytest.mark.asyncio()
async def test_fallback_not_used_when_same_as_primary():
    client = _make_client(fallback_model="gpt-4o")
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=_rate_limited_response())
        mock_get_client.return_value = mock_http

        with pytest.raises(LLMError):
            await client.chat([{"role": "user", "content": "hi"}])

    assert mock_http.post.await_count == 3  # 只跑主模型重试
