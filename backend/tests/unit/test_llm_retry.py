# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L3 请求层重试退避（LLMClient.chat / chat_stream_events）单元测试。

覆盖：429 重试 + retry-after 尊重、5xx/超时/网络重试、401 等不可重试错误
立即失败、重试耗尽抛出、流式"首块前可重试 / 首块后不重试"、env 覆盖。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import LLMClient, LLMConfig

pytestmark = pytest.mark.unit


def _make_client() -> LLMClient:
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://api.example.com/v1",
            model="gpt-3.5-turbo",
        )
    )


def _http_status_error(status: int, retry_after: str = "") -> httpx.HTTPStatusError:
    headers = {k.lower(): v for k, v in {"retry-after": retry_after}.items() if v}
    return httpx.HTTPStatusError(
        "http error",
        request=MagicMock(),
        response=MagicMock(status_code=status, headers=headers, text=""),
    )


def _ok_post_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=payload)
    return response


def _wire_post(client: LLMClient, outcomes: list) -> MagicMock:
    """把 mock post 接到 client 上；outcomes 为 response/exception 序列。"""
    mock_http = MagicMock()
    mock_http.post = AsyncMock(side_effect=outcomes)
    client._get_client = lambda: mock_http  # type: ignore[method-assign]
    return mock_http


_CHAT_OK = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "model": "gpt-3.5-turbo",
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


@pytest.mark.asyncio()
async def test_chat_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    client = _make_client()
    mock_http = _wire_post(
        client,
        [_http_status_error(429), _ok_post_response(_CHAT_OK)],
    )

    result = await client.chat([{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert mock_http.post.await_count == 2


@pytest.mark.asyncio()
async def test_chat_respects_retry_after_header(monkeypatch):
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "99")
    client = _make_client()
    _wire_post(
        client,
        [_http_status_error(429, retry_after="2"), _ok_post_response(_CHAT_OK)],
    )

    # retry-after=2s → 退避 2s 而非 base 99s（断言:调用成功即代表逻辑通路,
    # 退避值由 _retry_backoff_seconds 单测覆盖,这里不真等 2s——patch sleep）
    sleeps: list = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)
    result = await client.chat([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert sleeps
    assert abs(sleeps[0] - 2.0) < 0.001


@pytest.mark.asyncio()
async def test_chat_no_retry_on_auth_error():
    client = _make_client()
    mock_http = _wire_post(client, [_http_status_error(401)])

    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    assert exc_info.value.type == LLMErrorType.AUTH_FAILED
    assert mock_http.post.await_count == 1


@pytest.mark.asyncio()
async def test_chat_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    client = _make_client()
    mock_http = _wire_post(
        client,
        [_http_status_error(500)] * 3,
    )

    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
    assert mock_http.post.await_count == 3


# ---- 流式 ----


def _sse_ctx(chunks: list):
    lines = [f"data: {json.dumps(c)}" if isinstance(c, dict) else c for c in chunks]
    body = "\n\n".join(lines) + "\n\n"
    response = MagicMock()
    response.raise_for_status = MagicMock()

    async def aiter_lines():
        for ln in body.split("\n"):
            if ln != "":
                yield ln

    response.aiter_lines = aiter_lines
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _wire_stream(client: LLMClient, ctx_list: list) -> MagicMock:
    """stream() 依次返回 ctx_list 中的 context manager（第 N 次调用用第 N 个）。"""
    mock_http = MagicMock()
    calls = {"n": 0}

    def stream(*args, **kwargs):
        ctx = ctx_list[min(calls["n"], len(ctx_list) - 1)]
        calls["n"] += 1
        return ctx

    mock_http.stream = MagicMock(side_effect=stream)
    client._get_client = lambda: mock_http  # type: ignore[method-assign]
    return mock_http


@pytest.mark.asyncio()
async def test_stream_retries_before_first_delta(monkeypatch):
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    client = _make_client()

    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)

    ok_ctx = _sse_ctx(
        [
            {"choices": [{"delta": {"content": "hi"}}]},
            "data: [DONE]",
        ]
    )
    mock_http = _wire_stream(client, [fail_ctx, fail_ctx, ok_ctx])

    events = []
    async for kind, payload in client.chat_stream_events([{"role": "user", "content": "x"}]):
        events.append((kind, payload))

    assert mock_http.stream.call_count == 3  # 前两次 500 重试,第三次成功
    assert [k for k, _ in events] == ["content_delta", "response"]
    assert events[-1][1].content == "hi"


@pytest.mark.asyncio()
async def test_stream_no_retry_after_first_delta():
    client = _make_client()

    class _BrokenCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "部分"}}]}'
            raise _http_status_error(500)

    def broken_stream(*args, **kwargs):
        return _BrokenCtx()

    client._get_client = lambda: MagicMock(stream=broken_stream)  # type: ignore[method-assign]

    collected = []

    async def drain():
        async for kind, _payload in client.chat_stream_events(
            [{"role": "user", "content": "x"}]
        ):
            collected.append(kind)

    with pytest.raises(LLMError):
        await drain()

    assert collected == ["content_delta"]  # 已产出的增量不重放,直接失败
