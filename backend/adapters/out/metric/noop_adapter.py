"""No-op 指标 adapter（测试用，不做任何事）。"""

from __future__ import annotations
from typing import Dict


class NoopMetricAdapter:
    """什么都不做的 MetricPort 实现。"""

    def counter(self, name: str, labels: Dict[str, str]) -> None:
        pass

    def histogram(self, name: str, value: float, labels: Dict[str, str]) -> None:
        pass

    def gauge(self, name: str, value: float, labels: Dict[str, str]) -> None:
        pass
