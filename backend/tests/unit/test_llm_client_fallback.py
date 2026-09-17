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


# ===== 2026-09 修复: chat_stream_events 的 fallback 语义 =====
# 旧实现条件写反: 已产出增量反而切 fallback 从零重放(内容重复),
# 重试耗尽且未产出任何增量(降级核心场景)反而不降级。以下用例钉住
# 与 chat() 同口径的语义:
#   1. 未产出任何增量 + 可重试错误 + 重试耗尽 → 降级 fallback;
#   2. 已产出增量 → 无条件终止(不重试、不降级、不重放);
#   3. 非可重试错误(401) → 直接抛, 不降级。


class _StreamCM:
    """``client.stream(...)`` 的假异步上下文管理器。"""

    def __init__(self, lines=None, raise_exc=None):
        self._lines = lines or []
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _rate_limited_exc():
    resp = _rate_limited_response()
    return httpx.HTTPStatusError("429", request=AsyncMock(), response=resp)


def _unauthorized_exc():
    resp = AsyncMock()
    resp.status_code = 401
    resp.text = "unauthorized"
    resp.headers = {}
    return httpx.HTTPStatusError("401", request=AsyncMock(), response=resp)


_SSE_OK = [
    'data: {"choices":[{"delta":{"content":"he"}}]}',
    'data: {"choices":[{"delta":{"content":"y"}}]}',
    "data: [DONE]",
]


@pytest.mark.asyncio()
async def test_stream_fallback_fires_when_nothing_yielded():
    """未产出任何增量 + 主模型重试耗尽 → 必须降级 fallback (旧实现反而不降级)。"""
    client = _make_client(fallback_model="gpt-4o-mini")
    seen = []
    cms = [_StreamCM(raise_exc=_rate_limited_exc()) for _ in range(3)]
    cms.append(_StreamCM(lines=_SSE_OK))
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = Mock()

        def _stream(method, url, json=None, **kwargs):
            seen.append(json["model"])
            return cms.pop(0)

        mock_http.stream = Mock(side_effect=_stream)
        mock_get_client.return_value = mock_http
        events = [
            evt async for evt in client.chat_stream_events([{"role": "user", "content": "hi"}])
        ]
    content = "".join(p for name, p in events if name == "content_delta")
    assert content == "hey"
    # 主模型 3 次 + fallback 1 次
    assert len(seen) == 4
    assert seen[-1] == "gpt-4o-mini"


@pytest.mark.asyncio()
async def test_stream_no_replay_after_content_yielded():
    """已产出 content_delta 后失败 → 终止; 不重试、不降级重放(防内容重复)。"""
    client = _make_client(fallback_model="gpt-4o-mini")
    seen = []

    class _MidStreamFailCM(_StreamCM):
        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}'
            raise httpx.ReadTimeout("mid-stream failure")

    cms = [_MidStreamFailCM()]
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = Mock()

        def _stream(method, url, json=None, **kwargs):
            seen.append(json["model"])
            return cms.pop(0)

        mock_http.stream = Mock(side_effect=_stream)
        mock_get_client.return_value = mock_http

        async def _drain():
            async for _evt in client.chat_stream_events(
                [{"role": "user", "content": "hi"}]
            ):
                pass

        with pytest.raises(LLMError):
            await _drain()
    # TIMEOUT 可重试但已出增量 → 一次尝试即终止, 不打 fallback
    assert len(seen) == 1
    assert seen[0] == "gpt-4o"


@pytest.mark.asyncio()
async def test_stream_no_fallback_for_non_retryable():
    """401 鉴权失败 → 直接抛, 不降级 fallback (换模型也无济于事)。"""
    client = _make_client(fallback_model="gpt-4o-mini")
    seen = []
    cms = [_StreamCM(raise_exc=_unauthorized_exc())]
    with patch.object(client, "_get_client") as mock_get_client:
        mock_http = Mock()

        def _stream(method, url, json=None, **kwargs):
            seen.append(json["model"])
            return cms.pop(0)

        mock_http.stream = Mock(side_effect=_stream)
        mock_get_client.return_value = mock_http

        async def _drain_auth():
            async for _evt in client.chat_stream_events(
                [{"role": "user", "content": "hi"}]
            ):
                pass

        with pytest.raises(LLMError) as exc_info:
            await _drain_auth()
    assert exc_info.value.type == LLMErrorType.AUTH_FAILED
    assert len(seen) == 1
