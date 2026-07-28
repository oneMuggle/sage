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
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.data.settings_repo import SettingsRepository
from backend.services.permission_gate import get_permission_gate
from backend.tools.permissions import SETTINGS_KEY_RULES, parse_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/permissions", tags=["permissions"])


class ApprovalAnswerBody(BaseModel):
    """POST answer 请求体。"""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    remember: bool = False


def _persist_remembered_rule(tool_name: str, approved: bool) -> None:
    """remember=true 时把决定追加为持久化规则。

    失败只记 warning——规则持久化失败不应让"已批准"的应答对前端变失败
    （本次执行已经放行了）。
    """
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
async def list_pending_approvals() -> List[Dict[str, Any]]:
    """列出当前挂起的审批请求（gate 未初始化时返回空列表）。"""
    gate = get_permission_gate()
    if gate is None:
        return []
    return [req.to_dict() for req in gate.pending()]


@router.post("/{request_id}/answer")
async def answer_approval(request_id: str, body: ApprovalAnswerBody) -> Dict[str, Any]:
    """应答一个挂起的审批请求。

    错误语义（HTTP 恒为 200，ok 字段区分成败——与前端既有流式错误处理一致）:

    - gate 未初始化          → ``{"ok": false, "error": "permission_gate_not_initialized"}``
    - id 未知 / 已过期       → ``{"ok": false, "error": "unknown_or_expired"}``
    """
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


__all__ = ["router"]
