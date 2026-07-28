"""工具审批 REST 路由（M1 工具安全加固）。

前端契约（与 agent 流的 ``permission_request`` 事件配套）:

- ``GET /api/v1/permissions/pending``
    → ``[ApprovalRequest, ...]``（JSON 列表，形态同流事件的
    ``permission_request`` 字段；断线重连后用来补拉挂起对话框）。

- ``POST /api/v1/permissions/{request_id}/answer``
    body ``{"approved": bool, "remember": bool}``
    → ``{"ok": true}`` 或 ``{"ok": false, "error": "<reason>"}``

``remember=true`` 时把 ``PermissionRule(tool_pattern=<精确工具名>,
decision=allow|deny)`` 追加进 settings ``permission_rules``，下次 agent
运行构造 enforcer 时生效。

安全加固（安全评审 FIX-3 / FIX-4）:

- remember 持久化拒绝含 fnmatch 元字符（``* ? [ ]``）的工具名——工具名
  来自 LLM 工具调用，若把 ``"*"`` 落成规则等于永久 allow-all。
- 两个端点自带定向 Origin 守卫：带 ``Origin`` 头且不在白名单 → 403。
  背景：后端既有 CORS 配置是 ``allow_origins=["*"]``（全局问题，不在本
  里程碑内改），因此审批这种高权限端点必须自己挡住第三方网页的
  drive-by 请求。无 ``Origin`` 头（同源 / curl / python）放行——本地
  桌面应用的常态。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.data.settings_repo import SettingsRepository
from backend.services.permission_gate import get_permission_gate
from backend.tools.permissions import SETTINGS_KEY_RULES, parse_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/permissions", tags=["permissions"])

#: fnmatch 元字符——remember 持久化的 tool_pattern 含这些字符即拒绝。
#: 规则层用 fnmatch 匹配工具名，``"*"`` 会变成匹配一切工具的 allow-all
#: 规则（通配符规则注入）；``?`` / ``[ ]`` 同理可构造宽匹配。
_FNMATCH_METACHAR_RE = re.compile(r"[*?\[\]]")

#: 审批路由的 Origin 白名单。Electron 开发模式 ``loadURL`` 加载
#: ``http://localhost:1420``（见 electron/main.ts VITE_DEV_URL），打包后
#: ``loadFile`` 的 Origin 为 ``file://``；tauri 两形态为兼容保留。
_ALLOWED_ORIGINS = frozenset(
    {
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "file://",
        "tauri://localhost",
        "https://tauri.localhost",
    }
)


class ApprovalAnswerBody(BaseModel):
    """POST answer 请求体。"""

    approved: bool
    remember: bool = False

    class Config:
        # pydantic v1/v2 双兼容写法（Win7 LTS 分支用 v1）；
        # v2-only 的 ConfigDict / model_config 会在 v1 下静默失效。
        extra = "forbid"


def forbidden_origin_response(request: Request) -> Optional[JSONResponse]:
    """Origin 守卫：带 Origin 头且不在白名单 → 403 响应；否则 None（放行）。

    无 ``Origin`` 头视为同源 / 非浏览器客户端（curl、python、Electron
    同源请求），直接放行——本应用是本地桌面后端，不依赖浏览器 CORS 预检。

    本守卫供所有高权限 gate 路由复用（M2 part B: question_routes 导入本
    函数，不复制实现）。
    """
    origin = request.headers.get("origin")
    if origin is not None and origin not in _ALLOWED_ORIGINS:
        logger.warning(
            "审批路由拒绝非白名单 Origin: origin=%s path=%s", origin, request.url.path
        )
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "forbidden_origin"},
        )
    return None


def _persist_remembered_rule(tool_name: str, approved: bool) -> None:
    """remember=true 时把决定追加为持久化规则。

    安全闸（FIX-3）: ``tool_name`` 含 fnmatch 元字符（``* ? [ ]``）时
    静默降级为不记住——工具名来自 LLM 工具调用，原样落成 fnmatch pattern
    会让 ``"*"`` 变成永久 allow-all 规则。本次应答照常成功（approved 已
    作用于当次请求），只是不持久化，并记 warning。

    其它失败也只记 warning——规则持久化失败不应让"已批准"的应答对前端
    变失败（本次执行已经放行了）。
    """
    if _FNMATCH_METACHAR_RE.search(tool_name):
        logger.warning(
            "拒绝持久化含 fnmatch 元字符的审批规则（降级为不记住）: tool_name=%r",
            tool_name,
        )
        return
    try:
        repo = SettingsRepository()
        existing = parse_rules(repo.get_json(SETTINGS_KEY_RULES))
        rules_payload: List[Dict[str, Any]] = [r.to_dict() for r in existing]
        rules_payload.append(
            {
                "tool_pattern": tool_name,
                "decision": "allow" if approved else "deny",
            }
        )
        repo.set_json(SETTINGS_KEY_RULES, rules_payload, category="permissions")
        logger.info(
            "已持久化审批规则: tool=%s decision=%s (共 %d 条)",
            tool_name,
            "allow" if approved else "deny",
            len(rules_payload),
        )
    except Exception as exc:  # noqa: BLE001 — 持久化失败不阻塞应答
        logger.warning("持久化审批规则失败: %s", exc)


@router.get("/pending")
async def list_pending_approvals(request: Request) -> List[Dict[str, Any]]:
    """列出当前挂起的审批请求（gate 未初始化时返回空列表）。"""
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden  # type: ignore[return-value]
    gate = get_permission_gate()
    if gate is None:
        return []
    return [req.to_dict() for req in gate.pending()]


@router.post("/{request_id}/answer")
async def answer_approval(
    request_id: str, body: ApprovalAnswerBody, request: Request
) -> Dict[str, Any]:
    """应答一个挂起的审批请求。

    错误语义（HTTP 恒为 200，ok 字段区分成败——与前端既有流式错误处理一致；
    Origin 守卫例外，返回真正的 403）:

    - Origin 不在白名单      → HTTP 403 ``{"ok": false, "error": "forbidden_origin"}``
    - gate 未初始化          → ``{"ok": false, "error": "permission_gate_not_initialized"}``
    - id 未知 / 已过期       → ``{"ok": false, "error": "unknown_or_expired"}``
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden  # type: ignore[return-value]

    gate = get_permission_gate()
    if gate is None:
        return {"ok": False, "error": "permission_gate_not_initialized"}

    req = gate.get_request(request_id)
    if req is None:
        return {"ok": False, "error": "unknown_or_expired"}

    resolved = gate.answer(request_id, body.approved, body.remember)
    if not resolved:
        return {"ok": False, "error": "unknown_or_expired"}

    if body.remember:
        _persist_remembered_rule(req.tool_name, body.approved)

    return {"ok": True}


__all__ = ["router", "forbidden_origin_response"]
