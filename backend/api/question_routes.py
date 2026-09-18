"""用户提问 REST 路由（M2 part B: AskUserQuestion）。

前端契约（与 agent 流的 ``ask_user_question`` 事件配套）:

- ``GET /api/v1/questions/pending``
    → ``[QuestionRequest, ...]``（JSON 列表，形态同流事件的
    ``user_question`` 字段；断线重连后用来补拉挂起对话框）。

- ``POST /api/v1/questions/{request_id}/answer``
    body ``{"answers": ["<label>", ...], "custom": "<自由文本>|null"}``
    → ``{"ok": true}`` 或 ``{"ok": false, "error": "<reason>"}``

错误语义与 permission_routes 完全一致（HTTP 恒 200 + ok 字段，Origin
守卫例外返回真 403）。Origin 守卫直接**复用** permission_routes 的
``forbidden_origin_response``，不复制实现。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.api.permission_routes import forbidden_origin_response
from backend.services.question_gate import get_question_gate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questions", tags=["questions"])


class QuestionAnswerBody(BaseModel):
    """POST answer 请求体。

    - answers: 选中的选项 label 列表（可为空 —— Escape 空提交 = 超时语义）
    - custom:  "其他"自由文本（可为 null）
    """

    answers: List[str] = []
    custom: Optional[str] = None

    class Config:
        # pydantic v1/v2 双兼容写法（Win7 LTS 分支用 v1）；
        # v2-only 的 ConfigDict / model_config 会在 v1 下静默失效。
        extra = "forbid"


@router.get("/pending")
async def list_pending_questions(request: Request) -> Any:
    """列出当前挂起的提问请求（gate 未初始化时返回空列表）。"""
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden
    gate = get_question_gate()
    if gate is None:
        return []
    return [req.to_dict() for req in gate.pending()]


@router.post("/{request_id}/answer")
async def answer_question(
    request_id: str, body: QuestionAnswerBody, request: Request
) -> Dict[str, Any]:
    """应答一个挂起的提问请求。

    错误语义（HTTP 恒为 200，ok 字段区分成败——与 permission_routes 一致；
    Origin 守卫例外，返回真正的 403）:

    - Origin 不在白名单      → HTTP 403 ``{"ok": false, "error": "forbidden_origin"}``
    - gate 未初始化          → ``{"ok": false, "error": "question_gate_not_initialized"}``
    - id 未知 / 已过期       → ``{"ok": false, "error": "unknown_or_expired"}``
    """
    forbidden = forbidden_origin_response(request)
    if forbidden is not None:
        return forbidden  # type: ignore[return-value]

    gate = get_question_gate()
    if gate is None:
        return {"ok": False, "error": "question_gate_not_initialized"}

    resolved = gate.answer(request_id, body.answers, body.custom)
    if not resolved:
        return {"ok": False, "error": "unknown_or_expired"}

    return {"ok": True}


__all__ = ["router"]
