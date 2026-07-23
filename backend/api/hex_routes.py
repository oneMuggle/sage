# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (list[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
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
from typing import List, Optional

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
    """Hex 路径的 PUT /settings 请求体。

    字段契约（双层校验设计，Pydantic v1 win7 兼容）：

    - **Pydantic 层**（本类）：声明类型边界 + ``extra="forbid"`` 拒白名单外字段。
      顶层 13 个 AppSettings 字段 + 3 个 legacy 字段。
    - **canonical shape 层**（``validate_settings_shape``）：校验嵌套白名单
      + 拒绝残留 snake_case。两条不互冗余：Pydantic 给 OpenAPI docs + 顶层
      类型校验，canonical 给嵌套结构 + snake_case 翻译。
    - **legacy 字段**（``api_base_url`` / ``api_key`` / ``model``）：保留以兼容
      旧客户端调用（如 ``test_audit_log.py``）。handler 收到后只用作审计
      ``changed_fields`` 占位 + 日志标记，**不**写入 settings 存储。

    win7 Note: Pydantic v1 不支持 ``model_config = {"extra": ...}`` 字典写法,
    必须用 ``class Config: extra = ...``。
    """

    class Config:
        extra = "forbid"

    # ----- AppSettings 13 fields (canonical, src/entities/setting/types.ts) -----
    # noqa: N815 — camelCase 是为了与 AppSettings TypeScript interface 字段一一对齐；
    # 字段名经过 to_camel/validate_settings_shape 链路进入存储。
    streaming: Optional[bool] = None
    autoMemory: Optional[bool] = None  # noqa: N815
    confirmDelete: Optional[bool] = None  # noqa: N815
    compactMode: Optional[bool] = None  # noqa: N815
    endpoints: Optional[List[dict]] = None
    modelSelections: Optional[dict] = None  # noqa: N815
    maxContext: Optional[int] = None  # noqa: N815
    temperature: Optional[float] = None
    proxyMode: Optional[str] = None  # noqa: N815  # 'system' | 'custom' | 'direct'
    proxyUrl: Optional[str] = None  # noqa: N815
    tlsVersion: Optional[str] = None  # noqa: N815  # '1.2' | '1.3'
    wiki: Optional[dict] = None
    version: Optional[str] = None

    # ----- Legacy fields (deprecated, 兼容旧客户端, 不写入存储) -----
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None  # noqa: S105 — 字段名占位；不存储
    model: Optional[str] = None


class SettingsResponse(BaseModel):
    """Hex 路径的 PUT /settings 响应体。"""

    status: str = "ok"
    changed_fields: List[str] = []
    data: Optional[dict] = None  # GET 时填这里


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

    与 legacy 路径对齐：合并现有设置后翻译为 camelCase，并校验完整白名单。
    Legacy 字段（api_base_url / api_key / model）仅进入审计 changed_fields，
    不写入存储。
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    payload = req.dict(exclude_none=True)

    # 分离 legacy 字段 vs canonical 字段
    legacy_keys = {"api_base_url", "api_key", "model"}
    legacy_present = [k for k in payload if k in legacy_keys]
    canonical_payload = {k: v for k, v in payload.items() if k not in legacy_keys}

    from backend.data.settings_canonicalizer import to_camel, validate_settings_shape
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        existing = repo.get_json("app_settings")
    except (ValueError, TypeError):
        existing = {}
    # JSON 损坏 / 非 dict 时（如 list / str）→ fallback 到空 dict，避免 merge 时炸
    if not isinstance(existing, dict):
        existing = {}
    camel_merged = to_camel({**existing, **canonical_payload})
    try:
        validate_settings_shape(camel_merged)
    except ValueError as exc:
        logger.warning(f"[HEX REQ {request_id}] /settings rejected unknown field: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repo.set_json("app_settings", camel_merged, category="general")

    # 审计：仅记录字段名，不记录值；api_key 永不进 audit payload (但进 changed_fields 占位)
    changed_fields = list(canonical_payload)
    if "api_key" in payload:
        changed_fields.append("api_key")  # 占位标记
    # legacy 字段加在尾部以保留 audit_log 测试期望的顺序
    changed_fields.extend(legacy_present)
    logger.info(f"[HEX REQ {request_id}] /settings updated: changed={changed_fields}")

    svc.events.emit(
        "settings_changed",
        {"changed_fields": changed_fields, "request_id": request_id},
    )
    return SettingsResponse(status="ok", changed_fields=changed_fields)


@router.get("/settings")
async def get_settings() -> Optional[dict]:
    """读取持久化 settings，并把历史 snake_case 残留翻译为 camelCase。

    不存在或 JSON 损坏时返回 null，前端继续使用 DEFAULT_SETTINGS。
    非 dict 类型（如 list / str）也视为损坏，返回 None。
    """
    from backend.data.settings_canonicalizer import (
        detect_legacy_snake_pollution,
        to_camel,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        raw = repo.get_json("app_settings")
    except (ValueError, TypeError):
        return None
    if raw is None:
        return None
    # get_json 可返回任意合法 JSON（list / str / num）；app_settings 必须是 dict
    if not isinstance(raw, dict):
        return None
    detect_legacy_snake_pollution(raw)
    return to_camel(raw)


# ==================== 通用 KV /preferences/{key} 端点（白名单） ====================
#
# 用于替代前端的 localStorage 主题/会话 id 存储，仅暴露白名单内的 key。
# 非白名单 key 返回 400，避免 preferences 表被任意写入污染。


class PreferenceItem(BaseModel):
    """通用 KV /preferences/{key} 请求/响应体。"""

    value: Optional[str] = None
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
    parent_id: Optional[str] = None


class SessionUpdate(BaseModel):
    """Hex 路径 PATCH /sessions/{id} 请求体(局部更新,字段均可选)。"""

    title: Optional[str] = None
    is_pinned: Optional[bool] = None


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


@router.get("/sessions", response_model=List[dict])
async def list_sessions(
    limit: int = 100,
    offset: int = 0,
    svc: SessionService = Depends(get_session_service),
) -> List[dict]:
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


@router.get("/sessions/{session_id}/messages", response_model=List[dict])
async def list_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    svc: SessionService = Depends(get_session_service),
) -> List[dict]:
    """Hex 路径 GET /sessions/{id}/messages:列出会话消息(转 dict)。"""
    return await svc.list_messages(session_id, limit=limit, offset=offset)
