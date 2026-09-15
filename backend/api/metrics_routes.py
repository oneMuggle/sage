"""Prometheus /metrics 端点 (独立挂载, 与 API_MODE 解耦)。

L8 PR-A (2026-09-09): 历史 metrics 端点位于 hex_routes, 仅在
API_MODE=hex 时挂载。默认 legacy 模式下 /api/v1/metrics 不存在,
Prometheus / Grafana 无法直接接入。本模块把 metrics 端点从 hex_routes
抽出, 挂在 main app 上, 与 API_MODE 无关。

行为保持不变 (PG3.1):
- 当 ChatService 装配的 metrics 是 PrometheusMetricAdapter 实例 → 输出
  Prometheus text-format 字节流。
- 其它 adapter (如测试环境的 NoopMetricAdapter) → HTTP 200 + 空 body。
- 不调用 LLM, 不产生新事件, 仅读取 ChatService 装配的 adapter 状态。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.api.hex_routes import get_chat_service
from backend.application.services.chat_service import ChatService

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(svc: ChatService = Depends(get_chat_service)) -> Response:
    """Prometheus 指标端点（text/plain）。"""
    adapter = svc.metrics
    if isinstance(adapter, PrometheusMetricAdapter):
        return Response(content=adapter.render(), media_type=adapter.content_type)
    return Response(content=b"", media_type="text/plain; charset=utf-8")
