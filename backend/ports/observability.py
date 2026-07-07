"""可观测性端口（指标 + 事件）。

- ``MetricPort``：Prometheus 风格指标（counter / histogram / gauge）。
  P3.1 阶段会注册 9 个核心指标。
- ``EventPort`` ：业务事件（用于审计、调试、外部 hook）。
"""

from __future__ import annotations

from typing import Any, Dict, Protocol


class MetricPort(Protocol):
    """Prometheus 风格指标端口。"""

    def counter(self, name: str, labels: Dict[str, str]) -> None:
        """单调递增计数。"""
        ...

    def histogram(self, name: str, value: float, labels: Dict[str, str]) -> None:
        """分布观察（一般用于时延/响应大小）。"""
        ...

    def gauge(self, name: str, value: float, labels: Dict[str, str]) -> None:
        """当前值（可增可减，如队列长度、连接数）。"""
        ...


class EventPort(Protocol):
    """业务事件端口。"""

    def emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        """发出一个事件。"""
        ...
