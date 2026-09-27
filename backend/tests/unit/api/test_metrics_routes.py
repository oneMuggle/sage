"""R69 — metrics 路由单元测试。

直接调用路由函数（依赖参数手工注入）。覆盖：Prometheus 适配器透出
text-format、非 Prometheus 适配器空 body 两条路径。
"""

from __future__ import annotations

import pytest

from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.api import metrics_routes as mr

pytestmark = pytest.mark.unit


class _FakePrometheus(PrometheusMetricAdapter):
    """绕过真实构造，仅保留 isinstance 识别与渲染输出。"""

    def __init__(self):
        pass

    @property
    def content_type(self):
        return "text/plain; version=0.0.4; charset=utf-8"

    def render(self):
        return b"sage_tests_total 1"


class _FakeSvc:
    def __init__(self, adapter):
        self.metrics = adapter


def test_metrics_prometheus_adapter_renders_text_format():
    resp = mr.metrics(svc=_FakeSvc(_FakePrometheus()))
    assert resp.body == b"sage_tests_total 1"
    assert "text/plain" in resp.media_type


def test_metrics_non_prometheus_adapter_returns_empty_body():
    class _Noop:
        pass

    resp = mr.metrics(svc=_FakeSvc(_Noop()))
    assert resp.body == b""
    assert resp.media_type == "text/plain; charset=utf-8"
