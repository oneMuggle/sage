"""Prometheus 指标 adapter（骨架，P3.1 完善）。"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class PrometheusMetricAdapter:
    """MetricPort 的 Prometheus 实现。"""

    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or CollectorRegistry()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, Gauge] = {}

    def counter(self, name: str, labels: dict[str, str]) -> None:
        if name not in self._counters:
            self._counters[name] = Counter(
                name, "auto", labelnames=list(labels.keys()), registry=self._registry
            ).labels(**labels)
        self._counters[name].inc()

    def histogram(self, name: str, value: float, labels: dict[str, str]) -> None:
        if name not in self._histograms:
            self._histograms[name] = Histogram(
                name, "auto", labelnames=list(labels.keys()), registry=self._registry
            ).labels(**labels)
        self._histograms[name].observe(value)

    def gauge(self, name: str, value: float, labels: dict[str, str]) -> None:
        if name not in self._gauges:
            self._gauges[name] = Gauge(
                name, "auto", labelnames=list(labels.keys()), registry=self._registry
            ).labels(**labels)
        self._gauges[name].set(value)
