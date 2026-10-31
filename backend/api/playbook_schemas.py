"""Pydantic request/response models for `/api/v1/playbooks` routes (2026-10-31)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class BuiltinPlaybookListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbooks: List[Dict[str, Any]] = Field(default_factory=list)


class BuiltinPlaybookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook: Dict[str, Any]


class PlaybookCurrentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bound: bool
    playbook: Optional[Dict[str, Any]] = None
    source: Optional[str] = None
    version: Optional[int] = None
    spec_hash: Optional[str] = None
    state: Dict[str, Any] = Field(default_factory=dict)
    suggested: Optional[Dict[str, Any]] = None
    audit: Optional[Dict[str, Any]] = None


class PlaybookBindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook_id: Optional[str] = Field(default=None, max_length=128)
    spec: Optional[Dict[str, Any]] = None
    source: Optional[str] = Field(default=None, max_length=256)


class PlaybookStageConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str = Field(min_length=1, max_length=128)


class PlaybookActionsApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: List[Dict[str, Any]] = Field(default_factory=list)


class PlaybookActionsApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    errors: List[Dict[str, str]] = Field(default_factory=list)
    checkpoint_created: bool = False
    audit: Optional[Dict[str, Any]] = None


class PlaybookAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook: Dict[str, Any] = Field(default_factory=dict)
    current_stage: Optional[str] = None
    detected_stage: Dict[str, Any] = Field(default_factory=dict)
    stages: List[Dict[str, Any]] = Field(default_factory=list)
    overall: Dict[str, Any] = Field(default_factory=dict)
    scanned_at: int = 0


class PlaybookExportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str
    filename: str
    content: Any


class PlaybookImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: Dict[str, Any]
    project_id: Optional[str] = Field(default=None, max_length=128)


class PlaybookImportPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook: Dict[str, Any]
    scaffold: Dict[str, Any] = Field(default_factory=dict)
    diff: Dict[str, Any] = Field(default_factory=dict)


class PlaybookImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: Dict[str, Any]
    project_id: Optional[str] = Field(default=None, max_length=128)
    conflict: str = Field(default="save_as_new", pattern="^(replace|merge|save_as_new)$")


class PlaybookAuthorPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: Dict[str, Any] = Field(default_factory=dict)
    use_llm: bool = True


class PlaybookAuthorPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    playbook: Dict[str, Any]
    rationale: str
    llm_available: bool
    source: str


__all__ = [
    "BuiltinPlaybookListResponse",
    "BuiltinPlaybookResponse",
    "PlaybookActionsApplyRequest",
    "PlaybookActionsApplyResponse",
    "PlaybookAuditResponse",
    "PlaybookAuthorPreviewRequest",
    "PlaybookAuthorPreviewResponse",
    "PlaybookBindRequest",
    "PlaybookCurrentResponse",
    "PlaybookExportResponse",
    "PlaybookImportPreviewRequest",
    "PlaybookImportPreviewResponse",
    "PlaybookImportRequest",
    "PlaybookStageConfirmRequest",
]
