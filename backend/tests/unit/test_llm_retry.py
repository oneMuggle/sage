# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L3 请求层重试退避（LLMClient.chat / chat_stream_events）单元测试。

覆盖：429 重试 + retry-after 尊重、5xx/超时/网络重试、401 等不可重试错误
立即失败、重试耗尽抛出、流式"首块前可重试 / 首块后不重试"、env 覆盖。
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
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
    response.status_code = 200
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
    # 2026-10-13: 重试前推送 retry 事件（可见性优化）
    # 2026-11-03: 退避结束后推送 retry_attempt_started，前端切换到"在途等待"
    assert [k for k, _ in events] == [
        "retry",
        "retry_attempt_started",
        "retry",
        "retry_attempt_started",
        "content_delta",
        "response",
    ]
    assert events[-1][1].content == "hi"


@pytest.mark.asyncio()
async def test_stream_no_retry_after_first_delta():
    client = _make_client()

    class _BrokenCtx:
        status_code = 200

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


@pytest.mark.asyncio()
async def test_retry_total_budget_stops_retries(monkeypatch):
    """退避累计超过总时长预算 → 停止重试并用最后一次错误类型抛出。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "60")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "100")
    # 单次退避上限只在 app_settings 里可配（无 env），测试直接压模块常量。
    monkeypatch.setattr(
        "backend.core.legacy.llm_client._LLM_RETRY_MAX_DELAY_S", 60.0
    )

    clock = {"t": 0.0}
    monkeypatch.setattr("backend.core.legacy.llm_client._retry_now", lambda: clock["t"])

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    mock_http = _wire_post(client, [_http_status_error(504)] * 10)

    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    # 第 1 次失败后 0+60 <= 100 → 重试；第 2 次失败后 60+60 > 100 → 停止
    assert mock_http.post.await_count == 2
    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
    assert "预算" in exc_info.value.message
    # 停止原因必须可操作：带上已尝试次数与建议
    assert "已尝试 2/10 次" in exc_info.value.message
    assert "调大总时长预算" in exc_info.value.message


@pytest.mark.asyncio()
async def test_chat_rate_limited_error_carries_status_code(monkeypatch):
    """429 分类回传 status_code，供下游按状态码区分限流。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "1")
    client = _make_client()
    _wire_post(client, [_http_status_error(429)])

    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    assert exc_info.value.type == LLMErrorType.RATE_LIMITED
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio()
async def test_retry_event_includes_budget_fields(monkeypatch):
    """非流式重试事件携带总预算与本次等待后的剩余预算。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "60")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "200")
    monkeypatch.setattr(
        "backend.core.legacy.llm_client._LLM_RETRY_MAX_DELAY_S", 60.0
    )

    clock = {"t": 0.0}
    monkeypatch.setattr("backend.core.legacy.llm_client._retry_now", lambda: clock["t"])

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    _wire_post(client, [_http_status_error(504)] * 5)
    events = []

    with pytest.raises(LLMError):
        await client.chat(
            [{"role": "user", "content": "hi"}], retry_callback=events.append
        )

    # 200s 预算、每次退避 60s → 第 4 次失败时 180+60 > 200 停止；共 3 个重试事件
    assert len(events) == 3
    assert [e.budget_total_s for e in events] == [200.0, 200.0, 200.0]
    assert [e.budget_remaining_s for e in events] == [140.0, 80.0, 20.0]


@pytest.mark.asyncio()
async def test_retry_total_budget_disabled_when_zero(monkeypatch):
    """预算 0 = 不限，按 max_attempts 正常耗尽。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "0")
    client = _make_client()
    mock_http = _wire_post(client, [_http_status_error(500)] * 3)

    with pytest.raises(LLMError):
        await client.chat([{"role": "user", "content": "hi"}])

    assert mock_http.post.await_count == 3


@pytest.mark.asyncio()
async def test_stream_retry_total_budget_stops_retries(monkeypatch):
    """流式路径同样受总时长预算约束（与非流式对称）。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "60")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "100")
    monkeypatch.setattr(
        "backend.core.legacy.llm_client._LLM_RETRY_MAX_DELAY_S", 60.0
    )

    clock = {"t": 0.0}
    # 流式路径的预算起点复用 stream_started，因此整体替换模块 time 命名空间
    # （与 test_generation_stats 的 _fake_clock 同法），而非只 patch _retry_now。
    monkeypatch.setattr(
        "backend.core.legacy.llm_client.time",
        SimpleNamespace(monotonic=lambda: clock["t"], time=time.time),
    )

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)
    mock_http = _wire_stream(client, [fail_ctx] * 10)

    async def drain():
        async for _kind, _payload in client.chat_stream_events(
            [{"role": "user", "content": "x"}]
        ):
            pass

    with pytest.raises(LLMError) as exc_info:
        await drain()

    assert "预算" in exc_info.value.message
    assert "已尝试 2/10 次" in exc_info.value.message
    assert "调大总时长预算" in exc_info.value.message
    assert mock_http.stream.call_count == 2


@pytest.mark.asyncio()
async def test_stream_retry_event_includes_budget_fields(monkeypatch):
    """流式重试事件同样携带总预算与剩余预算（与非流式对称）。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "60")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "200")
    monkeypatch.setattr(
        "backend.core.legacy.llm_client._LLM_RETRY_MAX_DELAY_S", 60.0
    )

    clock = {"t": 0.0}
    monkeypatch.setattr(
        "backend.core.legacy.llm_client.time",
        SimpleNamespace(monotonic=lambda: clock["t"], time=time.time),
    )

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)
    _wire_stream(client, [fail_ctx] * 5)
    retry_events = []

    async def drain():
        async for kind, payload in client.chat_stream_events(
            [{"role": "user", "content": "x"}]
        ):
            if kind == "retry":
                retry_events.append(payload)

    with pytest.raises(LLMError):
        await drain()

    assert [e.budget_total_s for e in retry_events] == [200.0, 200.0, 200.0]
    assert [e.budget_remaining_s for e in retry_events] == [140.0, 80.0, 20.0]


@pytest.mark.parametrize(
    ("app_value", "env_value", "expected"),
    [
        (42, None, 42.0),  # app_settings 生效
        (42, "100", 100.0),  # env 覆盖 app_settings（调试/测试用，与其他参数一致）
        (0, None, 0.0),  # 0 = 不限
        (-1, None, 180.0),  # 非法值回退默认
    ],
)
def test_retry_settings_total_budget_sources(
    monkeypatch, app_value, env_value, expected
):
    """env > app_settings > 默认；非法值回退 180。"""
    monkeypatch.delenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", raising=False)
    if env_value is not None:
        monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", env_value)

    def fake_get_json(self, key):
        return {"llmRetryTotalBudgetS": app_value} if key == "app_settings" else None

    monkeypatch.setattr(
        "backend.data.settings_repo.SettingsRepository.get_json", fake_get_json
    )

    from backend.core.legacy.llm_client import _retry_settings

    assert _retry_settings()[3] == expected


# ---- 2026-11-03: 重试计时协议（elapsed / attempt_timeout / 在途事件） ----


@pytest.mark.asyncio()
async def test_stream_retry_events_include_elapsed_and_attempt_timeout(monkeypatch):
    """retry / retry_attempt_started 携带累计耗时与下一次尝试的超时上限。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "10")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "180")

    clock = {"t": 0.0}
    monkeypatch.setattr(
        "backend.core.legacy.llm_client.time",
        SimpleNamespace(monotonic=lambda: clock["t"], time=time.time),
    )

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    fail_ctx = _sse_ctx([])
    fail_response = fail_ctx.__aenter__.return_value

    def raise_500():
        raise _http_status_error(500)

    fail_response.raise_for_status = MagicMock(side_effect=raise_500)
    ok_ctx = _sse_ctx(
        [{"choices": [{"delta": {"content": "ok"}}]}, "data: [DONE]"]
    )
    _wire_stream(client, [fail_ctx, ok_ctx])

    retries = []
    started = []
    async for kind, payload in client.chat_stream_events(
        [{"role": "user", "content": "x"}]
    ):
        if kind == "retry":
            retries.append(payload)
        elif kind == "retry_attempt_started":
            started.append(payload)

    assert len(retries) == 1
    assert len(started) == 1
    r = retries[0]
    assert r.attempt == 1
    assert r.elapsed_s == 0.0
    assert r.delay == 10.0
    assert r.attempt_timeout_s is not None
    s = started[0]
    assert s.attempt == 2
    assert s.elapsed_s == 10.0
    assert s.budget_remaining_s == pytest.approx(170.0)
    assert s.attempt_timeout_s == pytest.approx(r.attempt_timeout_s)


@pytest.mark.asyncio()
async def test_retry_budget_caps_inflight_attempt_timeout(monkeypatch):
    """剩余预算不足一个完整动态超时时，单次请求超时被收紧到剩余预算。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "10")
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "2")
    monkeypatch.setenv("SAGE_LLM_RETRY_TOTAL_BUDGET_S", "100")

    clock = {"t": 0.0}
    monkeypatch.setattr(
        "backend.core.legacy.llm_client.time",
        SimpleNamespace(monotonic=lambda: clock["t"], time=time.time),
    )

    async def fake_sleep(delay: float) -> None:
        clock["t"] += delay

    monkeypatch.setattr("backend.core.legacy.llm_client.asyncio.sleep", fake_sleep)

    client = _make_client()
    mock_http = MagicMock()
    observed_timeouts = []

    async def _fail_after_60s(*args, **kwargs):
        observed_timeouts.append(mock_http.timeout)
        clock["t"] += 60.0
        raise _http_status_error(504)

    mock_http.post = AsyncMock(side_effect=_fail_after_60s)
    client._get_client = lambda: mock_http  # type: ignore[method-assign]

    with pytest.raises(LLMError) as exc_info:
        await client.chat([{"role": "user", "content": "hi"}])

    # 第 1 次在途 60s + 退避 2s → 剩余预算 38s，不足以再跑一次 60s 尝试
    assert mock_http.post.await_count == 2
    assert observed_timeouts[1].read == pytest.approx(38.0)
    assert "预算" in exc_info.value.message


@pytest.mark.asyncio()
async def test_complete_forwards_retry_callback(monkeypatch):
    """complete() 支持透传 retry_callback（压缩等后台调用可见性）。"""
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0")
    client = _make_client()
    _wire_post(
        client,
        [_http_status_error(500), _ok_post_response(_CHAT_OK)],
    )
    events = []

    result = await client.complete("hi", retry_callback=events.append)

    assert result == "ok"
    assert len(events) == 1
    assert events[0].attempt == 1
