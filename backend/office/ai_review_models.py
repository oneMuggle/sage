# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""Pydantic models for M3 AI review (spec rules + LLM merged into one issue list).

Contract notes:

* Every issue carries a :class:`AiReviewSource` so the UI can badge
  「规范书」 vs 「AI 补充」 vs 「内置规则」.
* Deterministic (rule pack) issues keep their anchor paragraph excerpt and
  rule id; LLM issues carry a rationale and an optional anchor index.
* History items mirror the ``office_ai_reviews`` table (see
  ``ai_review_history.py``) — ``created_at`` is the ms epoch.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

<<<<<<< HEAD
from pydantic import BaseModel, Field

# win7 py38 钉 pydantic 1.10，v2 专有符号必须走兼容垫片（2.x 下为 no-op）。
from backend.compat.win7.pydantic_compat import ConfigDict
=======
from pydantic import BaseModel, ConfigDict, Field
>>>>>>> origin/main

AiReviewSourceKind = Literal["spec", "llm", "builtin"]
AiReviewSeverity = Literal["error", "warning", "info"]
AiReviewScope = Literal["full", "selection", "section"]


class AiReviewSource(BaseModel):
    """Where one issue came from."""

    model_config = ConfigDict(extra="forbid")

    kind: AiReviewSourceKind
    spec_id: Optional[str] = Field(default=None, max_length=80)
    spec_name: Optional[str] = Field(default=None, max_length=200)
    rule_id: Optional[str] = Field(default=None, max_length=80)
    rule_pack_id: Optional[str] = Field(default=None, max_length=80)


class AiReviewLocation(BaseModel):
    """Paragraph anchor for jump/highlight in the preview."""

    model_config = ConfigDict(extra="forbid")

    paragraph_index: Optional[int] = Field(default=None, ge=0)
    paragraph_text: Optional[str] = Field(default=None, max_length=500)


class AiReviewIssue(BaseModel):
    """One merged issue (deterministic or LLM)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=120)
    severity: AiReviewSeverity = "warning"
    category: str = Field(default="content", max_length=40)
    message: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(default="", max_length=1000)
    rationale: str = Field(default="", max_length=1000)
    expected: Optional[str] = Field(default=None, max_length=500)
    actual: Optional[str] = Field(default=None, max_length=500)
    fixable: bool = False
    location: Optional[AiReviewLocation] = None
    source: AiReviewSource


class AiReviewSummary(BaseModel):
    """Counts + cost fields for one review run."""

    model_config = ConfigDict(extra="forbid")

    rules_checked: int = Field(default=0, ge=0)
    issue_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    info_count: int = Field(default=0, ge=0)
    spec_issue_count: int = Field(default=0, ge=0)
    llm_issue_count: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    model: Optional[str] = Field(default=None, max_length=120)
    prompt_tokens: Optional[int] = Field(default=None, ge=0)
    completion_tokens: Optional[int] = Field(default=None, ge=0)


class AiReviewResult(BaseModel):
    """POST /office/ai/review result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    doc_id: Optional[str] = None
    file_path: str
    scope: AiReviewScope = "full"
    spec_id: Optional[str] = None
    spec_name: Optional[str] = None
    summary: AiReviewSummary
    issues: List[AiReviewIssue] = Field(default_factory=list)
    warnings: List[Dict[str, str]] = Field(default_factory=list)


class AiReviewHistoryItem(BaseModel):
    """One ``office_ai_reviews`` row (GET /office/doc/{id}/ai-reviews)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    doc_id: str
    spec_id: Optional[str] = None
    model: Optional[str] = None
    scope: str
    issue_count: int = Field(default=0, ge=0)
    summary: Optional[Dict[str, Any]] = None
    duration_ms: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    created_at: int


class AiReviewHistoryResult(BaseModel):
    """GET /office/doc/{id}/ai-reviews result."""

    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    doc_id: str
    runs: List[AiReviewHistoryItem] = Field(default_factory=list)


__all__ = [
    "AiReviewHistoryItem",
    "AiReviewHistoryResult",
    "AiReviewIssue",
    "AiReviewLocation",
    "AiReviewResult",
    "AiReviewScope",
    "AiReviewSeverity",
    "AiReviewSource",
    "AiReviewSourceKind",
    "AiReviewSummary",
]
