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


def test_prometheus_counter():
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.counter("my_counter", {"route": "chat"})
    adapter.counter("my_counter", {"route": "chat"})
    output = generate_latest(registry).decode()
    assert "my_counter" in output
    assert 'route="chat"' in output


def test_prometheus_histogram():
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.histogram("my_hist", 1.5, {"kind": "prompt"})
    output = generate_latest(registry).decode()
    assert "my_hist" in output


def test_prometheus_gauge():
    registry = CollectorRegistry()
    adapter = PrometheusMetricAdapter(registry=registry)
    adapter.gauge("my_gauge", 42.0, {"scope": "global"})
    output = generate_latest(registry).decode()
    assert "my_gauge" in output
