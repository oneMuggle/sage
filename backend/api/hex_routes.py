"""新六边形 API 路由 — 调用 ChatService。

本模块是 P2 末的双轨：与 legacy_routes.py 并存。
默认 API_MODE=hex 时由 routes.py 加载本路由。

设计要点
--------

- **覆盖核心 chat 端点 + /metrics**：本模块暴露 ``POST /chat``
  和 ``GET /metrics`` 两个端点。其它端点（sessions / memory /
  evolution）由 legacy_routes 提供。P3+ 视情况逐步迁移。
- **DI 装配**：``get_chat_service()`` 是 FastAPI ``Depends`` 的工厂；
  ``main.py`` 启动时通过 ``app.dependency_overrides`` 注入真实实例，
  单元 / 集成测试可在 conftest 或用例里 override 注入 mock 实例。
- **错误透传**：``ChatService`` 不吞 ``LLMError``，由路由层翻译为
  HTTP 4xx/5xx 响应（与 legacy 端点的"HTTP 200 + error 字段"格式不同，
  因为 hex 路径是"明确失败就明确报错"，便于客户端统一处理）。
- **/metrics 端点**：PG3.1 落地。如果 ChatService 装配的 metrics
  adapter 是 ``PrometheusMetricAdapter``，输出 Prometheus text-format；
  否则（如测试环境的 ``NoopMetricAdapter``）返回 200 + 空 body。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.application.services.chat_service import ChatService
from backend.domain.errors import LLMError
from backend.domain.message import Message, Role

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Pydantic 模型 ====================


class ChatRequest(BaseModel):
    """Hex 路径的 /chat 请求体。"""

    session_id: str
    message: str


class ChatResponse(BaseModel):
    """Hex 路径的 /chat 响应体。"""

    session_id: str
    reply: str


# ==================== 依赖注入 ====================


def get_chat_service() -> ChatService:
    """工厂：返回一个装配好的 ``ChatService``。

    默认实现抛 ``NotImplementedError``——``main.py`` 必须通过
    ``app.dependency_overrides[get_chat_service] = lambda: real_svc``
    注入真实实例；测试可在 conftest 或用例里替换为 mock 实例。
    """
    raise NotImplementedError("get_chat_service() must be overridden via app.dependency_overrides")


# ==================== 聊天 API ====================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    """Hex 路径的 /chat 端点：把请求体翻译成 ``Message`` 后调 ``ChatService.run_turn``。

    错误处理：
    - ``LLMError``: 返回 HTTP ``exc.status_code or 502``（LLM 端故障）+ ``detail`` 字段
    - 其它未预期错误: 返回 HTTP 500 + 通用 detail
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info(
        f"[HEX REQ {request_id}] /chat received: session_id={req.session_id[:8]}..., "
        f"message_len={len(req.message)}"
    )

    user_msg = Message(role=Role.USER, content=req.message)
    try:
        msgs = await svc.run_turn(req.session_id, user_msg)
    except LLMError as exc:
        logger.warning(
            f"[HEX REQ {request_id}] /chat LLM error: type={exc.type.value}, "
            f"message={exc.message}"
        )
        raise HTTPException(
            status_code=exc.status_code or 502,
            detail={
                "type": exc.type.value,
                "message": exc.message,
                "status_code": exc.status_code,
                "retry_after": exc.retry_after,
            },
        ) from exc
    except Exception:
        logger.exception(f"[HEX REQ {request_id}] /chat unexpected error")
        raise HTTPException(
            status_code=500,
            detail={"type": "unknown", "message": "服务内部错误"},
        )

    assistant = next((m for m in reversed(msgs) if m.role == Role.ASSISTANT), None)
    if assistant is None:
        logger.error(f"[HEX REQ {request_id}] /chat no assistant response in messages")
        raise HTTPException(
            status_code=500,
            detail={"type": "no_assistant_response", "message": "no assistant response"},
        )

    return ChatResponse(session_id=req.session_id, reply=assistant.content)


# ==================== Prometheus /metrics 端点（PG3.1） ====================


@router.get("/metrics")
def metrics(svc: ChatService = Depends(get_chat_service)) -> Response:
    """Prometheus 指标端点（text/plain）。

    行为：
    - 当 ``svc.metrics`` 是 ``PrometheusMetricAdapter`` 实例时，输出
      Prometheus 标准的 text-format 字节流（含 9 个预注册指标的
      ``# HELP`` / ``# TYPE`` 行）。
    - 其它 adapter（如测试环境的 ``NoopMetricAdapter``）→ 返回
      HTTP 200 + 空 body（``text/plain``）。

    注意：本端点**不**走 ChatService 业务逻辑，纯粹读 ChatService
    装配的 metrics adapter；不产生新事件 / 不调用 LLM。
    """
    adapter = svc.metrics
    if isinstance(adapter, PrometheusMetricAdapter):
        return Response(content=adapter.render(), media_type=adapter.content_type)
    return Response(content=b"", media_type="text/plain; charset=utf-8")
