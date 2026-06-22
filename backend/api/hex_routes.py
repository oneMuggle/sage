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
from sage_core import LLMError, Message, Role
from sage_core.exceptions import SessionNotFoundError

from backend.adapters.out.metric.prometheus_adapter import PrometheusMetricAdapter
from backend.application.services.chat_service import ChatService
from backend.application.services.session_service import SessionService

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


class SettingsRequest(BaseModel):
    """Hex 路径的 PUT /settings 请求体（PG3.2）。

    所有字段可选；为 ``None`` 表示该字段未变更。``api_key`` 永远不应
    在审计日志中明文落盘（adapter 侧负责脱敏），本路由层只关心
    "哪些字段被改"，不持久化值。

    PG3.2 升级（2026-06-22）：``model_config = ConfigDict(extra="allow")``
    以接受前端的 ``AppSettings`` 完整字段（version / endpoints /
    modelSelections / streaming 等）。``api_key`` 仍走白名单脱敏审计。
    """

    model_config = {"extra": "allow"}

    api_base_url: str | None = None
    api_key: str | None = None  # noqa: S105 — 字段名占位；不存储
    model: str | None = None


class SettingsResponse(BaseModel):
    """Hex 路径的 PUT /settings 响应体。"""

    status: str = "ok"
    changed_fields: list[str] = []
    data: dict | None = None  # GET 时填这里


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


# ==================== PUT /settings 端点（PG3.2 — settings_changed 审计） ====================


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(
    req: SettingsRequest,
    request: Request,
    svc: ChatService = Depends(get_chat_service),
) -> SettingsResponse:
    """Hex 路径的 settings 更新端点 + persist + emit 审计事件。

    PG3.2 升级（2026-06-22）：
    - 持久化到 preferences 表的 app_settings key
    - 仍 emit settings_changed 审计事件（api_key 字段不进 payload）
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = req.model_dump(exclude_none=True)

    # 持久化到 SQLite
    from backend.data.settings_repo import SettingsRepository

    SettingsRepository().set_json("app_settings", payload, category="general")

    # 审计：仅记录字段名，不记录值；api_key 永不进 audit
    changed_fields = [k for k in payload if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")  # 占位标记
    logger.info(f"[HEX REQ {request_id}] /settings updated: changed={changed_fields}")

    svc.events.emit(
        "settings_changed",
        {"changed_fields": changed_fields, "request_id": request_id},
    )
    return SettingsResponse(status="ok", changed_fields=changed_fields)


@router.get("/settings")
async def get_settings() -> dict | None:
    """读取持久化的 settings；不存在返回 null（前端走 DEFAULT_SETTINGS）。

    说明（PG3.2）：本端点**不**用 ``response_model=SettingsResponse`` 包装，
    直接返回原始 payload（或 ``None``），以满足契约：
    - 无数据时 body 为字面量 ``null``（不是 ``{"data": null, ...}``）
    - 有数据时 body 为原始 dict（前端按 AppSettings 字段直接读）
    """
    from backend.data.settings_repo import SettingsRepository

    return SettingsRepository().get_json("app_settings")


# ==================== 通用 KV /preferences/{key} 端点（白名单） ====================
#
# 用于替代前端的 localStorage 主题/会话 id 存储，仅暴露白名单内的 key。
# 非白名单 key 返回 400，避免 preferences 表被任意写入污染。


class PreferenceItem(BaseModel):
    """通用 KV /preferences/{key} 请求/响应体。"""

    value: str | None = None
    value_type: str = "string"
    category: str = "general"


@router.get("/preferences/{key}", response_model=PreferenceItem)
async def get_preference(key: str) -> PreferenceItem:
    """通用 KV 读取（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    val = SettingsRepository().get(key)
    return PreferenceItem(value=val)


@router.put("/preferences/{key}", response_model=PreferenceItem)
async def put_preference(key: str, item: PreferenceItem) -> PreferenceItem:
    """通用 KV 写入（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    if item.value is not None:
        SettingsRepository().set(
            key, item.value, value_type=item.value_type, category=item.category
        )
    return item


# ============================================================================
# Sessions CRUD 端点（PG-A1）
# ============================================================================
#
# 历史：本模块原仅暴露 /chat、/metrics、/settings 三个端点；其余
# (/sessions、/memory、/evolution) 由 legacy_routes 提供。
# 2026-06-13 起按 docs/plans/2026-06-13_full-quality-optimization-v2.md
# 的 A1 阶段把 sessions 6 端点迁过来，调用 SessionService。
#
# 注意（PG-A1 GREEN-2）：
# - 本 PR 仅加端点 + 集成测试，**不**在 main.py 装配 SessionService。
# - main.py 默认 API_MODE 已临时改为 "legacy"（见 main.py 注释），
#   因此本模块的新 6 端点在 production 默认模式下不被注册，
#   无回归风险。
# - 集成测试显式设置 API_MODE=hex 走本模块。
# - SessionService 真正装配 (dependency_overrides) 在后续 PR 落地，
#   届时 main.py 的 API_MODE 默认值会从 "legacy" 切回 "hex"。
#


class SessionCreate(BaseModel):
    """Hex 路径 POST /sessions 请求体。"""

    title: str = "新对话"
    parent_id: str | None = None


class SessionUpdate(BaseModel):
    """Hex 路径 PATCH /sessions/{id} 请求体(局部更新,字段均可选)。"""

    title: str | None = None
    is_pinned: bool | None = None


# ==================== 依赖注入 ====================


def get_session_service() -> SessionService:
    """工厂:返回一个装配好的 ``SessionService``。

    默认实现抛 ``NotImplementedError``——``main.py`` 必须通过
    ``app.dependency_overrides[get_session_service] = lambda: real_svc``
    注入真实实例;测试可在 conftest 或用例里替换为 mock 实例。
    """
    raise NotImplementedError(
        "get_session_service() must be overridden via app.dependency_overrides"
    )


# ==================== 会话 API ====================


@router.post("/sessions", response_model=dict)
async def create_session(
    data: SessionCreate,
    svc: SessionService = Depends(get_session_service),
) -> dict:
    """Hex 路径 POST /sessions:创建并返回完整 dict(匹配 legacy 契约)。

    错误处理:
    - 极端情况(刚创就被外部删):返 500
    """
    sid = await svc.create_session(title=data.title)
    full = await svc.get_session(sid)
    if full is None:
        raise HTTPException(
            status_code=500,
            detail={"type": "internal", "message": "session created but not retrievable"},
        )
    return full


@router.get("/sessions", response_model=list[dict])
async def list_sessions(
    limit: int = 100,
    offset: int = 0,
    svc: SessionService = Depends(get_session_service),
) -> list[dict]:
    """Hex 路径 GET /sessions:分页列出(底层 storage 不支持分页,service 层切片)。"""
    return await svc.list_sessions(limit=limit, offset=offset)


@router.get("/sessions/{session_id}", response_model=dict)
async def get_session(
    session_id: str,
    svc: SessionService = Depends(get_session_service),
) -> dict:
    """Hex 路径 GET /sessions/{id}:单个会话;不存在返 404。"""
    result = await svc.get_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return result


@router.patch("/sessions/{session_id}", response_model=dict)
async def update_session(
    session_id: str,
    data: SessionUpdate,
    svc: SessionService = Depends(get_session_service),
) -> dict:
    """Hex 路径 PATCH /sessions/{id}:局部更新;会话不存在返 404。"""
    try:
        return await svc.update_session(session_id, title=data.title, is_pinned=data.is_pinned)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    svc: SessionService = Depends(get_session_service),
) -> dict:
    """Hex 路径 DELETE /sessions/{id}:成功返 {"status": "ok"};不存在 404。"""
    ok = await svc.delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}


@router.get("/sessions/{session_id}/messages", response_model=list[dict])
async def list_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    svc: SessionService = Depends(get_session_service),
) -> list[dict]:
    """Hex 路径 GET /sessions/{id}/messages:列出会话消息(转 dict)。"""
    return await svc.list_messages(session_id, limit=limit, offset=offset)
