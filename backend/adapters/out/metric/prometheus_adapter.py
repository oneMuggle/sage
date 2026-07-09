"""完整 Prometheus 指标 adapter（9 个核心指标）。

PG3.1 落地：按 spec § 6.1 注册 5 Counter + 3 Histogram + 1 Gauge，全部
在 ``__init__`` 预注册（保证 ``/metrics`` 输出里所有 9 个指标名以
``# HELP <name> ...`` 形式立即出现，即使它们尚未被触发）。

设计要点
--------

- **MetricPort 兼容**：保留 ``counter/histogram/gauge(name, value, labels)``
  入口；老代码（ChatService 旧指标名 ``chat_messages_total`` /
  ``tool_errors_total`` 等）调用进来时**静默忽略**，不抛错以保持
  ``MetricPort`` 协议稳定。
- **新 9 指标优先**：counter/histogram/gauge 内部按指标名路由到具体
  Prometheus 对象；同名 labelnames 在 ``__init__`` 锁定，避免运行期
  ``Duplicated timeseries`` 异常。
- **render()** 与 **registry**：暴露 ``generate_latest()`` 与底层
  ``CollectorRegistry``，便于 ``/metrics`` 端点直接输出。
"""

from __future__ import annotations
from typing import Dict, Optional

from typing import Dict, Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)


class PrometheusMetricAdapter:
    """9 个核心 Prometheus 指标的注册中心（spec § 6.1）。"""

    # 5 Counter
    HTTP_REQUESTS_TOTAL = "sage_http_requests_total"
    LLM_CALLS_TOTAL = "sage_llm_calls_total"
    TOOL_INVOCATIONS_TOTAL = "sage_tool_invocations_total"
    TOKENS_CONSUMED_TOTAL = "sage_tokens_consumed_total"
    ERRORS_TOTAL = "sage_errors_total"

    # 3 Histogram
    HTTP_REQUEST_DURATION = "sage_http_request_duration_seconds"
    LLM_CALL_DURATION = "sage_llm_call_duration_seconds"
    REACT_STEPS = "sage_react_steps_per_request"

    # 1 Gauge
    ACTIVE_SESSIONS = "sage_active_sessions"

    def __init__(self, registry: Optional[CollectorRegistry] = None) -> None:
        self._registry = registry or CollectorRegistry()

        # ---------- 5 Counter ----------
        self._http_requests = Counter(
            self.HTTP_REQUESTS_TOTAL,
            "HTTP 请求总数（按 route/method/status 分桶）",
            labelnames=["route", "method", "status"],
            registry=self._registry,
        )
        self._llm_calls = Counter(
            self.LLM_CALLS_TOTAL,
            "LLM 调用总数（按 model/provider/outcome 分桶）",
            labelnames=["model", "provider", "outcome"],
            registry=self._registry,
        )
        self._tool_invocations = Counter(
            self.TOOL_INVOCATIONS_TOTAL,
            "工具调用总数（按 tool/outcome 分桶）",
            labelnames=["tool", "outcome"],
            registry=self._registry,
        )
        self._tokens_consumed = Counter(
            self.TOKENS_CONSUMED_TOTAL,
            "LLM token 消耗总数（按 model/kind 分桶）",
            labelnames=["model", "kind"],
            registry=self._registry,
        )
        self._errors = Counter(
            self.ERRORS_TOTAL,
            "错误总数（按 layer/error_type 分桶）",
            labelnames=["layer", "error_type"],
            registry=self._registry,
        )

        # ---------- 3 Histogram ----------
        self._http_request_duration = Histogram(
            self.HTTP_REQUEST_DURATION,
            "HTTP 请求延迟（秒）",
            labelnames=["route"],
            registry=self._registry,
        )
        self._llm_call_duration = Histogram(
            self.LLM_CALL_DURATION,
            "LLM 调用延迟（秒）",
            labelnames=["model"],
            registry=self._registry,
        )
        self._react_steps = Histogram(
            self.REACT_STEPS,
            "ReAct 循环步数分布",
            buckets=[1, 2, 3, 5, 10, 20],
            registry=self._registry,
        )

        # ---------- 1 Gauge ----------
        self._active_sessions = Gauge(
            self.ACTIVE_SESSIONS,
            "当前活跃 session 数",
            registry=self._registry,
        )

    # ====================================================================== #
    # MetricPort 入口（counter/histogram/gauge）
    # ====================================================================== #

    def counter(self, name: str, labels: Dict[str, str]) -> None:
        """按指标名路由到具体 Counter。未知指标名 → 静默忽略。"""
        if name == self.HTTP_REQUESTS_TOTAL:
            self._http_requests.labels(**labels).inc()
        elif name == self.LLM_CALLS_TOTAL:
            self._llm_calls.labels(**labels).inc()
        elif name == self.TOOL_INVOCATIONS_TOTAL:
            self._tool_invocations.labels(**labels).inc()
        elif name == self.TOKENS_CONSUMED_TOTAL:
            self._tokens_consumed.labels(**labels).inc()
        elif name == self.ERRORS_TOTAL:
            self._errors.labels(**labels).inc()
        # 兼容旧指标名（PG2.9 阶段 ChatService 用的命名）：静默 no-op
        elif name in {
            "chat_messages_total",
            "tool_errors_total",
        }:
            pass
        # 其它未知指标：同样 no-op，保持 MetricPort 协议稳定

    def histogram(self, name: str, value: float, labels: Dict[str, str]) -> None:
        """按指标名路由到具体 Histogram。未知指标名 → 静默忽略。"""
        if name == self.HTTP_REQUEST_DURATION:
            self._http_request_duration.labels(**labels).observe(value)
        elif name == self.LLM_CALL_DURATION:
            self._llm_call_duration.labels(**labels).observe(value)
        elif name == self.REACT_STEPS:
            # REACT_STEPS 无 labelnames；labels 必须为空
            self._react_steps.observe(value)
        # 其它：no-op

    def gauge(self, name: str, value: float, labels: Dict[str, str]) -> None:
        """按指标名路由到具体 Gauge。未知指标名 → 静默忽略。"""
        if name == self.ACTIVE_SESSIONS:
            self._active_sessions.set(value)

    # ====================================================================== #
    # Prometheus 特定接口
    # ====================================================================== #

    def render(self) -> bytes:
        """返回 Prometheus text-format 字节流（用于 ``/metrics`` 端点）。"""
        return generate_latest(self._registry)

    @property
    def registry(self) -> CollectorRegistry:
        """暴露底层 ``CollectorRegistry``（便于多 adapter 共享/单测）。"""
        return self._registry

    @property
    def content_type(self) -> str:
        """``Content-Type`` header 值（Prometheus 标准 text-format）。"""
        return CONTENT_TYPE_LATEST
