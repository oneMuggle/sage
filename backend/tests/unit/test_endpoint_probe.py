# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""2026-11-26: 端点健康探测服务测试。"""

import httpx
import pytest

from backend.services.endpoint_health import (
    DEGRADED,
    HEALTHY,
    get_health_registry,
    reset_health_registry,
)
from backend.services.endpoint_probe import probe_endpoint

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean():
    reset_health_registry()
    yield
    reset_health_registry()


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio()
async def test_404_is_reachable_not_failure():
    reg = get_health_registry()
    reg.record_failure("ep1", "timeout")
    async with _client(lambda req: httpx.Response(404)) as client:
        outcome = await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "openai-compatible"},
            client=client,
        )
    assert outcome == "reachable"
    assert reg.get("ep1").status == DEGRADED  # 状态未被改动


@pytest.mark.asyncio()
async def test_success_restores_health():
    reg = get_health_registry()
    reg.record_failure("ep1", "timeout")
    reg.record_failure("ep1", "timeout")
    async with _client(lambda req: httpx.Response(200, json={"data": []})) as client:
        outcome = await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "openai-compatible"},
            client=client,
        )
    assert outcome == "success"
    assert reg.get("ep1").status == HEALTHY


@pytest.mark.asyncio()
async def test_500_records_failure():
    reg = get_health_registry()
    async with _client(lambda req: httpx.Response(500)) as client:
        outcome = await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "openai-compatible"},
            client=client,
        )
    assert outcome == "failure"
    assert reg.get("ep1").consecutive_failures == 1


@pytest.mark.asyncio()
async def test_ollama_uses_api_tags():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={})

    async with _client(handler) as client:
        await probe_endpoint(
            {"id": "ep1", "baseUrl": "http://x", "protocol": "ollama"}, client=client
        )
    assert seen["path"] == "/api/tags"
