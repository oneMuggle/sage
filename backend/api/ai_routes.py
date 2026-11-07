# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""P2 AI 侧栏端点：段落改写与文档对话。

只提供「纯文本进、纯文本出」的两个能力；审校与写回分别复用
``/office/ai/review`` 与 ``/office/ai/revise``，避免重复实现。

端点:

* ``POST /office/ai/rewrite`` — 单段/整篇的改写、润色、扩写、精简、翻译、摘要。
* ``POST /office/ai/chat``    — 带文档上下文的单轮对话（历史由前端维护）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.compat.win7.pydantic_compat import ConfigDict, PYDANTIC_V2

from backend.data.database import get_database
from backend.office.errors import OfficePathError
from backend.office.storage import validate_workspace
from backend.orchestration.llm_factory import (
    build_llm_client_from_settings,
    resolve_model_from_settings,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["office"])

MAX_TEXT_CHARS = 8000
MAX_CONTEXT_CHARS = 4000
MAX_HISTORY_ITEMS = 20
# pydantic v1 用 max_items 限制列表长度；v2 用 max_length（v1 会把 max_length
# 施加到每个元素上，语义不同）。
_HISTORY_LEN_KW = (
    {"max_length": MAX_HISTORY_ITEMS} if PYDANTIC_V2 else {"max_items": MAX_HISTORY_ITEMS}
)
MAX_HISTORY_CHARS = 4000

Instruction = Literal[
    "rewrite", "polish", "expand", "condense", "translate", "explain", "summarize", "custom"
]

_INSTRUCTION_TASKS = {
    "rewrite": "在不改变原意的前提下重写这段文字，使其更通顺、更专业。",
    "polish": "润色这段文字：修正语病与标点，保持原意与篇幅接近。",
    "expand": "在保持原意的前提下扩写这段文字，补充必要的解释与过渡。",
    "condense": "精简这段文字，保留全部关键信息，删除冗余表达。",
    "explain": "解释这段文字的含义与要点，输出简洁的解释而不是改写正文。",
    "summarize": "为这段文字生成摘要，只保留核心论点与结论。",
}


class RewriteRequest(BaseModel):
    """POST /office/ai/rewrite body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    instruction: Instruction
    target_lang: Optional[str] = Field(default=None, max_length=40)
    custom_instruction: Optional[str] = Field(default=None, max_length=1000)
    context_before: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)
    context_after: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)


class RewriteResult(BaseModel):
    ok: bool = True
    result: str
    model: Optional[str] = None


class ChatHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)


class ChatRequest(BaseModel):
    """POST /office/ai/chat body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    history: List[ChatHistoryItem] = Field(default_factory=list, **_HISTORY_LEN_KW)
    document_context: Optional[str] = Field(default=None, max_length=MAX_CONTEXT_CHARS)


class ChatResult(BaseModel):
    ok: bool = True
    reply: str
    model: Optional[str] = None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _validate_workspace(workspace_path: str) -> Path:
    try:
        return validate_workspace(Path(workspace_path))
    except OfficePathError as exc:
        # 只吞「路径不合法」这一类；其余异常照常冒泡，避免掩盖真实故障。
        logger.warning("ai rewrite workspace rejected: %s", type(exc).__name__)
        raise _error(404, "workspace_not_found", "工作区不存在或不可访问") from exc


def _assert_document_in_workspace(document_id: str, workspace: Path) -> None:
    conn = get_database().get_connection()
    row = conn.execute(
        "SELECT id FROM office_documents WHERE id = ? AND workspace_path = ?",
        (document_id, str(workspace)),
    ).fetchone()
    if row is None:
        raise _error(404, "document_not_found", "文档不存在或不属于该工作区")


def _build_rewrite_prompt(req: RewriteRequest) -> str:
    if req.instruction == "custom":
        task = (req.custom_instruction or "").strip()
        if not task:
            raise _error(422, "missing_custom_instruction", "custom 指令必须提供 custom_instruction")
    elif req.instruction == "translate":
        target = (req.target_lang or "").strip() or "中文"
        task = f"把这段文字翻译为{target}，只输出译文。"
    else:
        task = _INSTRUCTION_TASKS[req.instruction]

    parts = [task, "", "待处理文本：", "<<<", req.text, ">>>"]
    if req.context_before:
        parts += ["", "上一段（仅供理解，不要输出）：", "<<<", req.context_before, ">>>"]
    if req.context_after:
        parts += ["", "下一段（仅供理解，不要输出）：", "<<<", req.context_after, ">>>"]
    parts += ["", "只输出处理结果本身，不要解释、不要加引号或 Markdown 代码块。"]
    return "\n".join(parts)


def _build_chat_messages(req: ChatRequest) -> List[dict]:
    system = "你是文档写作助手，回答简洁、直接、可执行。不要编造文档中不存在的内容。"
    messages: List[dict] = [{"role": "system", "content": system}]
    if req.document_context:
        messages[0]["content"] = (
            system + "\n\n当前文档内容（按段落顺序，仅供参考）：\n" + req.document_context
        )
    for item in req.history[-MAX_HISTORY_ITEMS:]:
        messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": req.message})
    return messages


async def _complete(prompt: str) -> tuple:
    client = build_llm_client_from_settings()
    if client is None:
        raise _error(502, "llm_unavailable", "未配置可用的 LLM 模型")
    try:
        text = await client.complete(prompt)
    except Exception as exc:  # noqa: BLE001 — LLM 上游失败统一 502
        logger.warning("ai rewrite llm failed: %s", type(exc).__name__)
        raise _error(502, "llm_error", "LLM 调用失败，请稍后重试") from exc
    result = (text or "").strip()
    if not result:
        raise _error(502, "llm_empty", "LLM 返回了空结果")
    return result, resolve_model_from_settings()


@router.post("/rewrite", response_model=RewriteResult)
async def ai_rewrite_endpoint(req: RewriteRequest) -> RewriteResult:
    """按指令改写一段文本。不写文件、不改文档。"""
    workspace = _validate_workspace(req.workspace_path)
    _assert_document_in_workspace(req.document_id, workspace)
    prompt = _build_rewrite_prompt(req)
    result, model = await _complete(prompt)
    return RewriteResult(ok=True, result=result, model=model)


@router.post("/chat", response_model=ChatResult)
async def ai_chat_endpoint(req: ChatRequest) -> ChatResult:
    """带文档上下文的单轮问答。历史由前端维护并随请求下发。"""
    workspace = _validate_workspace(req.workspace_path)
    _assert_document_in_workspace(req.document_id, workspace)

    client = build_llm_client_from_settings()
    if client is None:
        raise _error(502, "llm_unavailable", "未配置可用的 LLM 模型")
    try:
        response = await client.chat(_build_chat_messages(req))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai chat llm failed: %s", type(exc).__name__)
        raise _error(502, "llm_error", "LLM 调用失败，请稍后重试") from exc
    reply = (getattr(response, "content", "") or "").strip()
    if not reply:
        raise _error(502, "llm_empty", "LLM 返回了空结果")
    model = getattr(response, "model", None)
    return ChatResult(ok=True, reply=reply, model=model if isinstance(model, str) else None)


__all__ = ["ChatRequest", "ChatResult", "RewriteRequest", "RewriteResult", "router"]
