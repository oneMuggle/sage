"""OpenTelemetry 工具（P3 启用，stdout 导出）。

提供全局 TracerProvider 初始化、Tracer 懒加载获取、优雅关闭三件套。
设计上与 logging 类似——``utils/otel.py`` 是叶子工具，不依赖
``application/`` 或 ``adapters/``，避免 import-linter 报六边形违规。

典型用法::

    from backend.utils.otel import get_tracer, init_tracing

    # 在应用启动时（main.py）调用一次：
    init_tracing(service_name="sage")

    # 在业务代码里：
    tracer = get_tracer("chat_service")
    with tracer.start_as_current_span("chat.run_turn") as span:
        span.set_attribute("session.id", session_id)
        ...
"""

from __future__ import annotations

from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# 模块级 provider 缓存（保持单例）
_provider: Optional[TracerProvider] = None


def init_tracing(service_name: str = "sage") -> TracerProvider:
    """初始化全局 TracerProvider。

    幂等：重复调用返回同一 provider，避免多次注册
    ``BatchSpanProcessor`` 导致 span 重复导出。

    Args:
        service_name: 资源属性 ``service.name`` 的值，用于在
            后端（如 Jaeger/Tempo）区分不同服务。

    Returns:
        全局唯一的 ``TracerProvider`` 实例。
    """
    global _provider
    if _provider is not None:
        return _provider

    resource = Resource.create({"service.name": service_name})
    _provider = TracerProvider(resource=resource)
    # stdout 导出（生产可换 OTLP；这里只走 ConsoleSpanExporter 即可）
    _provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(_provider)
    return _provider


def get_tracer(name: str = "sage") -> trace.Tracer:
    """获取一个 ``Tracer``（可延迟初始化）。

    如果应用启动时忘了调 ``init_tracing``，这里会兜底初始化一次，
    避免业务代码因顺序问题而抛错。

    Args:
        name: tracer 名称（通常用模块名，如 ``"chat_service"``）。

    Returns:
        OpenTelemetry ``Tracer`` 实例。
    """
    if _provider is None:
        init_tracing()
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """关闭 provider，flush 待导出 span。

    一般在应用退出钩子里调用，确保 ``BatchSpanProcessor`` 缓存的
    span 全部刷到 exporter 后再销毁 provider。
    """
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
