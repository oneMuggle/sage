"""验证 metric adapters 骨架。"""

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from backend.adapters.out.metric.noop_adapter import NoopMetricAdapter
from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter

pytestmark = pytest.mark.unit


def test_noop_counter():
    adapter = NoopMetricAdapter()
    adapter.counter("test", {"a": "1"})  # should not raise


def test_noop_histogram_gauge():
    adapter = NoopMetricAdapter()
    adapter.histogram("test", 1.0, {"a": "1"})
    adapter.gauge("test", 5.0, {"a": "1"})


# ----------------- PG3.1: 9 个核心指标预注册验证 -----------------


def test_prometheus_pre_registers_all_9_metrics():
    """9 个核心指标都在 __init__ 预注册（生成 /metrics 输出含 # HELP）。"""
    registry = CollectorRegistry()
    PrometheusMetricAdapter(registry=registry)
    output = generate_latest(registry).decode()
    expected = [
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
    for name in expected:
        assert f"# HELP {name}" in output, f"missing pre-registered metric: {name}"
        assert f"# TYPE {name}" in output, f"missing TYPE for metric: {name}"


def test_prometheus_render_returns_text_format():
    """render() 返回 Prometheus text-format 字节流。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    body = adapter.render()
    assert isinstance(body, bytes)
    assert b"sage_llm_calls_total" in body
    assert b"# HELP" in body
    assert b"# TYPE" in body


def test_prometheus_content_type_property():
    """content_type 属性暴露 Prometheus 标准 text-format。"""
    adapter = PrometheusMetricAdapter(registry=CollectorRegistry())
    ctype = adapter.content_type
    assert "text/plain" in ctype
    assert "version=" in ctype


def test_prometheus_counter_routes_to_specific_metric():
    """counter(name, labels) 路由到具体 9 指标之一。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.counter("sage_llm_calls_total", {"model": "x", "provider": "p", "outcome": "success"})
    adapter.counter("sage_llm_calls_total", {"model": "x", "provider": "p", "outcome": "success"})
    body = generate_latest(registry).decode()
    # Prometheus 输出按 label key 字典序排列
    assert 'sage_llm_calls_total{model="x",outcome="success",provider="p"} 2.0' in body


def test_prometheus_histogram_routes_to_specific_metric():
    """histogram(name, value, labels) 路由到具体 9 指标之一。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.histogram("sage_llm_call_duration_seconds", 1.5, {"model": "x"})
    body = generate_latest(registry).decode()
    assert "sage_llm_call_duration_seconds" in body
    assert 'model="x"' in body


def test_prometheus_gauge_routes_to_specific_metric():
    """gauge(name, value, labels) 路由到具体 9 指标之一。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.gauge("sage_active_sessions", 7.0, {})
    body = generate_latest(registry).decode()
    assert "sage_active_sessions 7.0" in body


def test_prometheus_unknown_counter_name_is_silent_noop():
    """counter 接到未知指标名不抛错（保持 MetricPort 协议稳定）。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    # 旧名 + 未知名都不应抛错
    adapter.counter("chat_messages_total", {"role": "user"})
    adapter.counter("unknown_legacy_metric", {"k": "v"})
    # 不应出现在 # HELP 列表中
    output = generate_latest(registry).decode()
    assert "chat_messages_total" not in output
    assert "unknown_legacy_metric" not in output


def test_prometheus_unknown_histogram_name_is_silent_noop():
    """histogram 接到未知指标名不抛错。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.histogram("unknown_hist", 1.0, {"k": "v"})
    output = generate_latest(registry).decode()
    assert "unknown_hist" not in output


def test_prometheus_unknown_gauge_name_is_silent_noop():
    """gauge 接到未知指标名不抛错。"""
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.gauge("unknown_gauge", 5.0, {"k": "v"})
    output = generate_latest(registry).decode()
    assert "unknown_gauge" not in output
