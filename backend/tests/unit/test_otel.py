"""验证 OpenTelemetry 工具与 trace_id 注入。"""
from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.unit


def test_init_tracing_is_idempotent():
    """init_tracing 多次调用返回同一 provider。

    二次调用不会重新注册 ``BatchSpanProcessor``，避免 span 重复导出。
    """
    from backend.utils.otel import init_tracing

    # 强制清理以保证测试可重复（其他测试可能已初始化过）
    from backend.utils import otel as _otel_mod

    _otel_mod._provider = None
    p1 = init_tracing("test-svc-1")
    p2 = init_tracing("test-svc-2")
    # 第二次调用仍返回首次的 provider（不重新初始化）
    assert p1 is p2


def test_get_tracer_returns_tracer():
    """get_tracer 返回 Tracer 实例。"""
    from backend.utils.otel import get_tracer

    t = get_tracer("test")
    assert t is not None
    assert hasattr(t, "start_as_current_span")


def test_span_context_manager_works():
    """start_as_current_span 上下文管理器工作。"""
    from opentelemetry import trace

    from backend.utils.otel import get_tracer

    tracer = get_tracer("test")
    with tracer.start_as_current_span("test-span") as span:
        # span 应该处于 recording 状态
        assert span.is_recording()
        span.set_attribute("test.key", "value")
        # 同一 thread 内 get_current_span 应返回该 span
        current = trace.get_current_span()
        assert current is span
    # 出 with 块后 span 已结束；get_current_span 应为 non-recording
    after = trace.get_current_span()
    assert not after.is_recording()


def test_trace_id_filter_handles_no_active_span():
    """无活跃 span 时 filter 不抛错。"""
    from backend.utils.logging import TraceIdFilter

    f = TraceIdFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="hi",
        args=(),
        exc_info=None,
    )
    # filter 应返回 True（不阻断日志）
    assert f.filter(record) is True
    # filter 兜底注入了占位符 trace_id / span_id（避免 format KeyError）
    assert hasattr(record, "trace_id")
    assert hasattr(record, "span_id")
    assert record.trace_id == "-"
    assert record.span_id == "-"


def test_trace_id_filter_injects_active_span_ids():
    """有活跃 span 时 filter 注入 trace_id / span_id。"""
    from backend.utils.logging import TraceIdFilter
    from backend.utils.otel import get_tracer

    tracer = get_tracer("test")
    with tracer.start_as_current_span("with-trace") as span:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="x",
            lineno=1,
            msg="hi",
            args=(),
            exc_info=None,
        )
        f = TraceIdFilter()
        f.filter(record)
        ctx = span.get_span_context()
        expected_trace = format(ctx.trace_id, "032x")
        expected_span = format(ctx.span_id, "016x")
        assert record.trace_id == expected_trace
        assert record.span_id == expected_span
