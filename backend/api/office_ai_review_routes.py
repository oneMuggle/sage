# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""M3 AI 审校路由（合并审校 + 历史记录）.

端点:

* ``POST /office/ai/review`` — 对 Word 文档跑一次合并审校(规范书规则 + 可选
  LLM 语义审校)，并在完成后写入一条历史审计记录。
* ``GET  /office/doc/{doc_id}/ai-reviews`` — 列出文档的审校历史。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database
from backend.office.ai_review import run_review_async
from backend.office.ai_review_history import list_for_document, record
from backend.office.ai_review_models import (
    AiReviewHistoryResult,
    AiReviewIssue,
    AiReviewResult,
)
from backend.office.errors import OfficeParseError, OfficePathError
from backend.office.path_safety import resolve_within
from backend.office.storage import get_document, snapshot_pre_edit, validate_workspace
from backend.office.word_revision_writer import apply_word_revisions

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
    max_size_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024
    )


class AiReviseRequest(BaseModel):
    """POST /office/ai/revise body.

    Applies a selection of AI review issues as tracked Word revisions.
    The pre-edit file is snapshotted first (best-effort) so the user can
    revert without going through the archive/restore path.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    doc_id: Optional[str] = Field(default=None, max_length=80)
    issues: List[AiReviewIssue] = Field(min_length=1, max_length=200)
    output_filename: Optional[str] = Field(default=None, max_length=500)
    author: str = Field(default="Sage", max_length=80)
    add_comments: bool = True


class AiReviseResult(BaseModel):
    """POST /office/ai/revise response."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    doc_id: Optional[str] = None
    snapshot_path: Optional[str] = None
    source_path: str
    output_path: str
    overwritten: bool = False
    planned: int = 0
    applied: int = 0
    skipped: int = 0
    changes: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────


def _doc_in_workspace(
    conn: sqlite3.Connection, doc_id: str, workspace: str
) -> bool:
    """文档必须登记在给定工作区内——防止跨工作区绑定/污染历史."""
    try:
        row = conn.execute(
            "SELECT id FROM office_documents WHERE id = ? AND workspace_path = ?",
            (doc_id, workspace),
        ).fetchone()
    except sqlite3.Error:
        return False
    return row is not None


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
    if req.doc_id and not _doc_in_workspace(
        get_database().get_connection(), req.doc_id, str(workspace)
    ):
        raise OfficeParseError("文档不存在或不属于该工作区")
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
    doc_id: str,
    workspace_path: Optional[str] = None,
    limit: int = 50,
) -> AiReviewHistoryResult:
    """列出文档的审校历史(最新在前).

    传入 ``workspace_path`` 时文档必须属于该工作区，否则返回空历史
    （不暴露其它工作区文档是否存在）。``limit`` 收敛到 [1, 200]。
    """
    limit = max(1, min(int(limit), 200))
    conn = get_database().get_connection()
    if workspace_path:
        workspace = validate_workspace(Path(workspace_path))
        if not _doc_in_workspace(conn, doc_id, str(workspace)):
            return AiReviewHistoryResult(ok=True, doc_id=doc_id, runs=[])
    rows = list_for_document(conn, doc_id, limit=limit)
    return AiReviewHistoryResult(ok=True, doc_id=doc_id, runs=rows)


@router.post("/ai/revise", response_model=AiReviseResult)
def ai_revise_endpoint(req: AiReviseRequest) -> AiReviseResult:
    """Apply selected AI review issues as tracked Word revisions.

    流程:

    1. 校验 ``file_path`` 落在工作区内、是文件、有登记的 ``doc_id``(可选).
    2. 若 ``doc_id`` 已登记,调 :func:`snapshot_pre_edit` 先做 pre-edit 快照
       (best-effort,失败不打断).
    3. 将每个 :class:`AiReviewIssue` 映射为 ``{find, replace, comment}`` 字典,
       ``actual``→find, ``expected``/``suggestion``→replace,跳过不可修复项.
    4. 调 :func:`apply_word_revisions` 写入修订痕迹(overwrite 或 output_filename).
    """
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    conn = get_database().get_connection()
    summary = None
    if req.doc_id:
        if not _doc_in_workspace(conn, req.doc_id, str(workspace)):
            raise OfficeParseError("文档不存在或不属于该工作区")
        summary = get_document(conn, req.doc_id)

    # Pre-edit snapshot (best-effort).
    snapshot_path: Optional[Path] = None
    if summary is not None:
        snapshot_path = snapshot_pre_edit(summary)

    # Convert issues to raw changes. Only issues with a concrete "actual"
    # anchor AND a replacement text (expected or suggestion) can be applied
    # as tracked revisions; the rest are surfaced to the caller as skipped.
    raw_changes: List[Dict[str, Any]] = []
    for issue in req.issues:
        find_text = issue.actual or ""
        replace_text = issue.expected or issue.suggestion or ""
        if not find_text or not replace_text or find_text == replace_text:
            continue
        raw_changes.append(
            {
                "find": find_text,
                "replace": replace_text,
                "comment": _build_comment(issue) if req.add_comments else "",
                "reason": issue.message,
            }
        )
    if not raw_changes:
        raise OfficeParseError("所选问题没有可应用的修订")

    overwrite = req.output_filename is None
    result = apply_word_revisions(
        file_path,
        raw_changes,
        req.output_filename,
        overwrite=overwrite,
        author=req.author,
        workspace_path=str(workspace),
        add_comments=req.add_comments,
    )
    return AiReviseResult(
        ok=result.ok,
        doc_id=req.doc_id,
        snapshot_path=str(snapshot_path) if snapshot_path else None,
        source_path=result.source_path,
        output_path=result.output_path,
        overwritten=result.overwritten,
        planned=result.planned,
        applied=result.applied,
        skipped=result.skipped,
        changes=[c.model_dump() for c in result.changes],
        warnings=result.warnings,
    )


def _build_comment(issue: AiReviewIssue) -> str:
    """Build a Word review comment from an AI review issue."""
    parts = [issue.message]
    if issue.rationale:
        parts.append(issue.rationale)
    source_kind = issue.source.kind
    if source_kind == "llm":
        parts.append("[AI]")
    elif source_kind == "spec" and issue.source.rule_id:
        parts.append(f"[spec:{issue.source.rule_id}]")
    return " — ".join(parts)[:1000]


__all__ = [
    "AiReviewRequest",
    "AiReviseRequest",
    "AiReviseResult",
    "ai_review_endpoint",
    "ai_review_history_endpoint",
    "ai_revise_endpoint",
    "router",
]
