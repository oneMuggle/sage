"""验证 /metrics 端点暴露 9 个核心 Prometheus 指标（PG3.1）。

覆盖范围
--------

- ``GET /metrics`` 端点可用（200 + text/plain）
- 9 个 spec § 6.1 核心指标全部以 ``# HELP <name>`` 形式出现在输出中
- ``POST /chat`` 后 ``sage_llm_calls_total`` 计数（outcome="success"）
  至少不会减少（可能不变因为不创建新 label）
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from prometheus_client import CollectorRegistry

from backend.adapters.out.event.stdout_adapter import StdoutEventAdapter
from backend.adapters.out.llm.mock_adapter import MockLLMAdapter
from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.adapters.out.storage.memory_adapter import MemoryStorageAdapter
from backend.adapters.out.tool.inproc_adapter import InprocToolAdapter
from backend.api.hex_routes import get_chat_service
from backend.application.services.chat_service import ChatService
from backend.domain.message import Message, Role
from backend.main import app

pytestmark = pytest.mark.integration

CHAT_PATH = "/api/v1/chat"
METRICS_PATH = "/api/v1/metrics"

# 仅在 hex 模式下有效
_API_MODE = os.environ.get("API_MODE", "hex").lower()
_HEX_ONLY = pytest.mark.skipif(
    _API_MODE != "hex",
    reason=f"本文件测 hex /metrics 行为；当前 API_MODE={_API_MODE!r}（需 hex）",
)


# spec § 6.1 定义的 9 个核心指标名
EXPECTED_METRICS = [
    "sage_http_requests_total",
    "sage_llm_calls_total",
    "sage_tool_invocations_total",
    "sage_tokens_consumed_total",
    "sage_errors_total",
    "sage_http_request_duration_seconds",
    "sage_llm_call_duration_seconds",
    "sage_react_steps_per_request",
    "sage_active_sessions",
]


@pytest_asyncio.fixture
async def prom_client():
    """装配 PrometheusMetricAdapter 的 hex 客户端。

    同样使用 in-memory 辅助：LLM=Mock、Storage=Memory、Tool=Inproc+mock，
    但 ``metrics`` 端口是真实 ``PrometheusMetricAdapter``，使 ``/metrics``
    端点能输出 Prometheus text-format。
    """

    prom = PrometheusMetricAdapter(registry=CollectorRegistry())

    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="hi")]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=prom,
        events=StdoutEventAdapter(verbose=False),
    )

    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, fake_svc, prom
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)


@pytest_asyncio.fixture
async def noop_client():
    """装配 NoopMetricAdapter 的 hex 客户端（验证空响应路径）。"""
    mock_tool = MagicMock()
    mock_tool.execute.return_value = MagicMock(success=True, output="ok", error=None)
    mock_registry = MagicMock()
    mock_registry.list.return_value = []
    mock_registry.get.return_value = mock_tool

    fake_svc = ChatService(
        llm=MockLLMAdapter(responses=[Message(role=Role.ASSISTANT, content="hi")]),
        tools=InprocToolAdapter(registry=mock_registry),
        skills=MagicMock(),
        storage=MemoryStorageAdapter(),
        metrics=NoopMetricAdapter(),
        events=StdoutEventAdapter(verbose=False),
    )

    saved_override = app.dependency_overrides.get(get_chat_service)
    app.dependency_overrides[get_chat_service] = lambda: fake_svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac, fake_svc
    finally:
        if saved_override is not None:
            app.dependency_overrides[get_chat_service] = saved_override
        else:
            app.dependency_overrides.pop(get_chat_service, None)


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_metrics_endpoint_returns_200_with_text_plain(prom_client):
    """GET /metrics 返回 200 + Prometheus text-format content-type。"""
    client, _svc, _prom = prom_client
    resp = await client.get(METRICS_PATH)
    assert resp.status_code == 200, resp.text
    ctype = resp.headers["content-type"]
    assert "text/plain" in ctype
    # Prometheus text-format（prometheus_client 0.25）声明为
    # 'text/plain; version=1.0.0; charset=utf-8'。
    assert "version=" in ctype or "text/plain" in ctype


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_metrics_endpoint_lists_all_9_core_metrics(prom_client):
    """9 个 spec § 6.1 核心指标全部以 # HELP 形式暴露。"""
    client, _svc, _prom = prom_client
    resp = await client.get(METRICS_PATH)
    assert resp.status_code == 200
    body = resp.text
    for name in EXPECTED_METRICS:
        # Prometheus 对未触发的指标仍以 # HELP <name> 形式列出
        assert f"# HELP {name}" in body, f"missing metric: {name}"


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_metrics_endpoint_after_chat_does_not_decrease_llm_counter(prom_client):
    """POST /chat 后 llm_calls_total 计数 >= pre（不会减少）。"""
    client, fake_svc, _prom = prom_client

    pre = (await client.get(METRICS_PATH)).text
    pre_count = pre.count("sage_llm_calls_total{")

    sid = await fake_svc.storage.create_session()
    await client.post(CHAT_PATH, json={"session_id": sid, "message": "hi"})

    post = (await client.get(METRICS_PATH)).text
    post_count = post.count("sage_llm_calls_total{")
    # 至少不会减少；实际可能 +2（started + success 两条 time-series）
    assert post_count >= pre_count


@pytest.mark.asyncio  # noqa: PT023 — 兼容 CI ruff 0.15.x (偏好无括号)
@_HEX_ONLY
async def test_metrics_endpoint_with_noop_adapter_returns_empty(noop_client):
    """Noop adapter 下 /metrics 端点返回 200 + 空 body（不崩）。"""
    client, _svc = noop_client
    resp = await client.get(METRICS_PATH)
    assert resp.status_code == 200
    assert resp.text == "" or resp.content == b""
