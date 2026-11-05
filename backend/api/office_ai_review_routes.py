# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M3 AI 审校路由（合并审校 + 历史记录）.

端点:

* ``POST /office/ai/review`` — 对 Word 文档跑一次合并审校(规范书规则 + 可选
  LLM 语义审校)，并在完成后写入一条历史审计记录。
* ``GET  /office/doc/{doc_id}/ai-reviews`` — 列出文档的审校历史。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database
from backend.office.ai_review import run_review_async
from backend.office.ai_review_history import list_for_document, record
from backend.office.ai_review_models import (
    AiReviewHistoryResult,
    AiReviewResult,
)
from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace

router = APIRouter(tags=["office"])


# ── request models ────────────────────────────────────────────────────


class AiReviewRequest(BaseModel):
    """POST /office/ai/review body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    doc_id: Optional[str] = Field(default=None, max_length=80)
    spec_id: Optional[str] = Field(default=None, max_length=80)
    scope: str = Field(default="full", max_length=20)
    use_llm: bool = True
    max_issues: int = Field(default=100, ge=1, le=300)
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


# ── endpoints ─────────────────────────────────────────────────────────


@router.post("/ai/review", response_model=AiReviewResult)
async def ai_review_endpoint(req: AiReviewRequest) -> AiReviewResult:
    """对一份 Word 文档跑「规范书 + LLM」合并审校.

    完成后调 :func:`ai_review_history.record` 写入历史(若 ``doc_id``
    已提供)。历史写入是 best-effort，失败不会打断响应。
    """
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    if file_path.stat().st_size > req.max_size_bytes:
        raise OfficeParseError(
            f"文档超过大小上限 {req.max_size_bytes} 字节"
        )
    result = await run_review_async(
        file_path,
        workspace=workspace,
        workspace_path=str(workspace),
        doc_id=req.doc_id,
        spec_id=req.spec_id,
        scope=req.scope,
        use_llm=req.use_llm,
        max_issues=req.max_issues,
    )
    if req.doc_id:
        record(
            req.doc_id,
            scope=result.scope,
            issue_count=result.summary.issue_count,
            spec_id=result.spec_id,
            model=result.summary.model,
            summary=(
                {
                    "error_count": result.summary.error_count,
                    "warning_count": result.summary.warning_count,
                    "info_count": result.summary.info_count,
                    "rules_checked": result.summary.rules_checked,
                    "spec_issue_count": result.summary.spec_issue_count,
                    "llm_issue_count": result.summary.llm_issue_count,
                }
            ),
            duration_ms=result.summary.duration_ms,
            prompt_tokens=result.summary.prompt_tokens,
            completion_tokens=result.summary.completion_tokens,
        )
    return result


@router.get(
    "/doc/{doc_id}/ai-reviews", response_model=AiReviewHistoryResult
)
def ai_review_history_endpoint(
    doc_id: str, workspace_path: Optional[str] = None, limit: int = 50
) -> AiReviewHistoryResult:
    """列出文档的审校历史(最新在前)."""
    if workspace_path:
        validate_workspace(Path(workspace_path))
    rows = list_for_document(get_database().get_connection(), doc_id, limit=limit)
    return AiReviewHistoryResult(ok=True, doc_id=doc_id, runs=rows)


__all__ = [
    "AiReviewRequest",
    "ai_review_endpoint",
    "ai_review_history_endpoint",
    "router",
]
