# ruff: noqa: UP006, UP007, UP035, UP045, SIM117 — release/win7 Python 3.8 兼容
# （py38 不支持括号多上下文 with）
"""2026-11-26: LLMClient 跨端点故障转移测试（非流式）。"""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from backend.core.errors import LLMError, LLMErrorType
from backend.core.legacy.llm_client import EndpointHop, FailoverEvent, LLMClient, LLMConfig
from backend.services.endpoint_health import HEALTHY, get_health_registry, reset_health_registry

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _fast_retry_and_clean_health(monkeypatch):
    monkeypatch.setattr("backend.core.legacy.llm_client._LLM_RETRY_MAX_DELAY_S", 0.01)
    monkeypatch.setenv("SAGE_LLM_RETRY_BASE_DELAY_S", "0.01")
    monkeypatch.setenv("SAGE_LLM_RETRY_MAX_ATTEMPTS", "2")
    reset_health_registry()
    yield
    reset_health_registry()


def _ok(model):
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


def _err(status):
    resp = AsyncMock()
    resp.status_code = status
    resp.text = "boom"
    resp.headers = {}
    resp.raise_for_status = Mock(
        side_effect=httpx.HTTPStatusError("boom", request=AsyncMock(), response=resp)
    )
    return resp


def _client(chain):
    return LLMClient(
        LLMConfig(
            provider="openai",
            api_key="k1",
            base_url="http://primary",
            model="m1",
            endpoint_id="ep1",
            endpoint_chain=[
                EndpointHop(
                    endpoint_id="ep1",
                    base_url="http://primary",
                    api_key="k1",
                    provider="openai",
                    model="m1",
                )
            ]
            + list(chain),
        )
    )


HOP2 = EndpointHop(
    endpoint_id="ep2",
    endpoint_name="Backup",
    base_url="http://backup",
    api_key="k2",
    provider="openai",
    model="m1",
)


@pytest.mark.asyncio()
async def test_first_hop_uses_chain_endpoint_credentials_when_primary_cooling():
    """HIGH 回归：chain[0] 不是 config 端点时，必须用 hop 的客户端/凭据。"""
    backup_hop = EndpointHop(
        endpoint_id="ep2",
        base_url="http://backup",
        api_key="k2",
        provider="openai",
        model="m1",
    )
    client = LLMClient(
        LLMConfig(
            provider="openai",
            api_key="k1",
            base_url="http://primary",
            model="m1",
            endpoint_id="ep1",
            endpoint_chain=[backup_hop],
        )
    )
    primary_http, backup = AsyncMock(), AsyncMock()
    backup.post = AsyncMock(return_value=_ok("m1"))
    with patch.object(client, "_get_client", return_value=primary_http), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert primary_http.post.await_count == 0
    assert backup.post.await_count == 1


@pytest.mark.asyncio()
async def test_rate_limited_primary_fails_over_to_next_endpoint():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(429))
    backup.post = AsyncMock(return_value=_ok("m1"))
    events = []
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        response = await client.chat(
            [{"role": "user", "content": "hi"}], failover_callback=events.append
        )
    assert response.content == "ok"
    assert backup.post.await_count == 1
    assert isinstance(events[0], FailoverEvent)
    assert events[0].from_endpoint == "ep1"
    assert events[0].to_endpoint == "ep2"
    assert get_health_registry().get("ep1").status != HEALTHY
    assert get_health_registry().get("ep2").status == HEALTHY


@pytest.mark.asyncio()
async def test_auth_failure_switches_immediately_without_retry():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(401))
    backup.post = AsyncMock(return_value=_ok("m1"))
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert primary.post.await_count == 1  # 401 不重试
    assert backup.post.await_count == 1


@pytest.mark.asyncio()
async def test_all_hops_fail_raises_error_naming_attempt_count():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(500))
    backup.post = AsyncMock(return_value=_err(503))
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        with pytest.raises(LLMError) as exc_info:
            await client.chat([{"role": "user", "content": "hi"}])
    assert exc_info.value.type == LLMErrorType.SERVER_ERROR
    assert "2 个端点" in exc_info.value.message


@pytest.mark.asyncio()
async def test_usage_recorded_for_serving_hop(monkeypatch):
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.post = AsyncMock(return_value=_err(429))
    backup.post = AsyncMock(return_value=_ok("m1"))
    recorded = []

    class _Tracker:
        def record(self, *args, **kwargs):
            recorded.append(kwargs.get("endpoint_id"))

    monkeypatch.setattr(
        "backend.services.usage_tracker.usage_tracker", _Tracker(), raising=False
    )
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        await client.chat([{"role": "user", "content": "hi"}])
    assert recorded
    assert recorded[-1] == "ep2"


@pytest.mark.asyncio()
async def test_fallback_model_stays_inside_primary_hop():
    hop2 = EndpointHop(
        endpoint_id="ep2",
        base_url="http://backup",
        api_key="k2",
        provider="openai",
        model="m1",
    )
    client = LLMClient(
        LLMConfig(
            provider="openai",
            api_key="k1",
            base_url="http://primary",
            model="m1",
            endpoint_id="ep1",
            fallback_model="mini",
            endpoint_chain=[
                EndpointHop(
                    endpoint_id="ep1",
                    base_url="http://primary",
                    api_key="k1",
                    provider="openai",
                    model="m1",
                    fallback_model="mini",
                ),
                hop2,
            ],
        )
    )
    primary, backup = AsyncMock(), AsyncMock()
    # 主跳：2 次主模型 + 2 次 fallback 全部 429 → 切到第二跳
    models = []

    async def _primary_post(path, json=None):
        models.append(json["model"])
        return _err(429)

    primary.post = AsyncMock(side_effect=_primary_post)
    backup.post = AsyncMock(return_value=_ok("m1"))
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        response = await client.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert models == ["m1", "m1", "mini", "mini"]
    assert backup.post.await_args_list[0].kwargs["json"]["model"] == "m1"


def _stream_ok(lines):
    class _Ctx:
        async def __aenter__(self):
            resp = AsyncMock()
            resp.status_code = 200
            resp.raise_for_status = Mock()

            async def _lines():
                for line in lines:
                    yield line

            resp.aiter_lines = lambda: _lines()
            return resp

        async def __aexit__(self, *args):
            return False

    return _Ctx()


@pytest.mark.asyncio()
async def test_stream_first_hop_uses_hop_client_when_chain_head_is_backup():
    backup_hop = EndpointHop(
        endpoint_id="ep2",
        base_url="http://backup",
        api_key="k2",
        provider="openai",
        model="m1",
    )
    client = LLMClient(
        LLMConfig(
            provider="openai",
            api_key="k1",
            base_url="http://primary",
            model="m1",
            endpoint_id="ep1",
            endpoint_chain=[backup_hop],
        )
    )
    primary, backup = AsyncMock(), AsyncMock()
    backup.stream = Mock(
        return_value=_stream_ok(
            [
                'data: {"model":"m1","choices":[{"delta":{"content":"ok"}}]}',
                "data: [DONE]",
            ]
        )
    )
    events = []
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        async for event in client.chat_stream_events(
            [{"role": "user", "content": "hi"}]
        ):
            events.append(event)
    assert ("content_delta", "ok") in events
    assert primary.stream.call_count == 0


@pytest.mark.asyncio()
async def test_stream_fails_over_before_first_delta():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()
    primary.stream = Mock(side_effect=httpx.ConnectError("down"))
    backup.stream = Mock(
        return_value=_stream_ok(
            [
                'data: {"model":"m1","choices":[{"delta":{"content":"ok"}}]}',
                "data: [DONE]",
            ]
        )
    )
    events = []
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        async for event in client.chat_stream_events(
            [{"role": "user", "content": "hi"}]
        ):
            events.append(event)
    kinds = [kind for kind, _ in events]
    assert "failover" in kinds
    assert ("content_delta", "ok") in events


@pytest.mark.asyncio()
async def test_stream_does_not_failover_after_first_delta():
    client = _client([HOP2])
    primary, backup = AsyncMock(), AsyncMock()

    class _BrokenCtx:
        async def __aenter__(self):
            resp = AsyncMock()
            resp.status_code = 200
            resp.raise_for_status = Mock()

            async def _lines():
                yield 'data: {"model":"m1","choices":[{"delta":{"content":"partial"}}]}'
                raise httpx.ReadError("cut")

            resp.aiter_lines = lambda: _lines()
            return resp

        async def __aexit__(self, *args):
            return False

    primary.stream = Mock(return_value=_BrokenCtx())
    backup.stream = Mock(return_value=_stream_ok(["data: [DONE]"]))
    with patch.object(client, "_get_client", return_value=primary), patch.object(
        client, "_get_client_for_hop", return_value=backup
    ):
        with pytest.raises(LLMError):  # noqa: PT012 — 断言块含 async for 驱动
            async for _event in client.chat_stream_events(
                [{"role": "user", "content": "hi"}]
            ):
                pass
    assert backup.stream.call_count == 0
