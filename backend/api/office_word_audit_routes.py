"""Word rule pack + deterministic audit routes (M2a)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.office.errors import OfficeParseError, OfficePathError, OfficeSizeLimitError
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace
from backend.office.word_audit import audit_word_document
from backend.office.word_batch_audit import audit_word_batch
from backend.office.word_fix import fix_word_document
from backend.office.word_render_audit import audit_word_render
from backend.office.word_revision_writer import (
    apply_word_revisions,
    build_revision_plan,
)
from backend.office.word_rule_extract import (
    extract_word_rules,
    extract_word_rules_async,
)
from backend.office.word_rulepack_models import (
    WordAuditFixResult,
    WordAuditResult,
    WordBatchAuditResult,
    WordRenderAuditResult,
    WordRevisionResult,
    WordRuleExtractionResult,
    WordRulePack,
    WordRulePackDetailResult,
    WordRulePackListResult,
    WordRulePackSummary,
)
from backend.office.word_rulepack_store import (
    DEFAULT_RULEPACK_ID,
    delete_rulepack,
    list_rulepacks,
    load_rulepack,
    save_rulepack,
)

router = APIRouter(prefix="/word", tags=["office"])


class WordAuditRequest(BaseModel):
    """POST /office/word/audit body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


class WordRulePackSaveRequest(BaseModel):
    """POST /office/word/rulepacks body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    pack: WordRulePack


class WordAuditFixRequest(BaseModel):
    """POST /office/word/audit/fix body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None
    output_filename: Optional[str] = Field(default=None, max_length=255)
    overwrite: bool = False
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


class WordRuleExtractRequest(BaseModel):
    """POST /office/word/rulepacks/extract body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    file_type: Literal["spec", "template"] = "spec"
    pack_id: str = Field(default="extracted-pack", min_length=1, max_length=80)
    pack_name: Optional[str] = Field(default=None, max_length=200)
    use_llm: bool = False
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


class WordRuleExtractSaveRequest(BaseModel):
    """POST /office/word/rulepacks/extract/save body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    pack: WordRulePack


class WordRevisionChangeRequest(BaseModel):
    """One requested tracked replacement."""

    model_config = ConfigDict(extra="forbid")

    rule_id: Optional[str] = Field(default=None, max_length=80)
    find: str = Field(min_length=1, max_length=2000)
    replace: str = Field(default="", max_length=2000)
    comment: str = Field(default="", max_length=1000)


class WordAuditReviseRequest(BaseModel):
    """POST /office/word/audit/revise body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None
    changes: Optional[List[WordRevisionChangeRequest]] = None
    output_filename: Optional[str] = Field(default=None, max_length=255)
    overwrite: bool = False
    author: str = Field(default="Sage", min_length=1, max_length=100)
    add_comments: bool = True
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


class WordAuditRenderRequest(BaseModel):
    """POST /office/word/audit/render body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str = Field(min_length=1, max_length=2000)
    expected_size: Optional[Literal["A4", "Letter"]] = None
    margins_cm: Optional[Dict[str, float]] = None
    allowed_fonts: Optional[List[str]] = None
    require_page_number: bool = False
    margin_tolerance_cm: float = Field(default=0.3, ge=0, le=5)
    page_number_band: float = Field(default=0.15, ge=0.01, le=0.5)
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


class WordBatchAuditRequest(BaseModel):
    """POST /office/word/audit/batch body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_paths: Optional[List[str]] = None
    pattern: str = Field(default="**/*.docx", max_length=500)
    max_files: int = Field(default=20, ge=1, le=100)
    rulepack_id: Optional[str] = Field(default=None, max_length=80)
    rulepack: Optional[WordRulePack] = None
    include_report: bool = True
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


def _check_size_limit(file_path: Path, max_size_bytes: int) -> None:
    actual_size = file_path.stat().st_size
    if actual_size > max_size_bytes:
        raise OfficeSizeLimitError(
            actual_size=actual_size, max_size=max_size_bytes, file_path=file_path
        )


@router.get("/rulepacks")
def list_rulepacks_endpoint(
    workspace_path: Optional[str] = None,
) -> WordRulePackListResult:
    """List built-in packs (plus workspace packs when a workspace is given)."""
    workspace = validate_workspace(Path(workspace_path)) if workspace_path else None
    result = list_rulepacks(workspace)
    return WordRulePackListResult(
        workspace_path=str(workspace) if workspace is not None else "",
        packs=[WordRulePackSummary(**item) for item in result["packs"]],
        warnings=result["warnings"],
    )


@router.get("/rulepacks/{pack_id}")
def get_rulepack_endpoint(
    pack_id: str, workspace_path: Optional[str] = None
) -> WordRulePackDetailResult:
    """Return one rule pack; workspace packs take precedence over built-ins."""
    workspace = validate_workspace(Path(workspace_path)) if workspace_path else None
    loaded = load_rulepack(workspace, pack_id)
    return WordRulePackDetailResult(
        workspace_path=str(workspace) if workspace is not None else "",
        origin=loaded["origin"],
        pack=loaded["pack"],
    )


@router.post("/rulepacks")
def save_rulepack_endpoint(req: WordRulePackSaveRequest) -> WordRulePackDetailResult:
    """Save a workspace rule pack (built-in ids are protected)."""
    workspace = validate_workspace(Path(req.workspace_path))
    pack = save_rulepack(workspace, req.pack)
    return WordRulePackDetailResult(
        workspace_path=str(workspace), origin="workspace", pack=pack
    )


@router.delete("/rulepacks/{pack_id}")
def delete_rulepack_endpoint(pack_id: str, workspace_path: str) -> dict:
    """Delete a workspace rule pack; built-in packs cannot be deleted."""
    workspace = validate_workspace(Path(workspace_path))
    return delete_rulepack(workspace, pack_id)


@router.post("/audit")
def audit_word_endpoint(req: WordAuditRequest) -> WordAuditResult:
    """Run deterministic rule checks and return anchored issues (read-only)."""
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    _check_size_limit(file_path, req.max_size_bytes)
    if req.rulepack is not None:
        pack = req.rulepack
    else:
        pack = load_rulepack(workspace, req.rulepack_id or DEFAULT_RULEPACK_ID)["pack"]
    return audit_word_document(file_path, pack, workspace_path=str(workspace))


@router.post("/audit/fix")
def fix_word_endpoint(req: WordAuditFixRequest) -> WordAuditFixResult:
    """Apply deterministic fixes, then re-audit the output (M2b)."""
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    _check_size_limit(file_path, req.max_size_bytes)
    if req.rulepack is not None:
        pack = req.rulepack
    else:
        pack = load_rulepack(workspace, req.rulepack_id or DEFAULT_RULEPACK_ID)["pack"]
    return fix_word_document(
        file_path,
        pack,
        req.output_filename,
        overwrite=req.overwrite,
        workspace_path=str(workspace),
    )


@router.post("/rulepacks/extract")
def extract_rulepack_endpoint(req: WordRuleExtractRequest) -> WordRuleExtractionResult:
    """Extract a draft rule pack from a spec or template document (M3a)."""
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    _check_size_limit(file_path, req.max_size_bytes)
    if req.use_llm:
        return asyncio.run(
            extract_word_rules_async(
                file_path,
                file_type=req.file_type,
                pack_id=req.pack_id,
                pack_name=req.pack_name,
                workspace_path=str(workspace),
                use_llm=True,
            )
        )
    return extract_word_rules(
        file_path,
        file_type=req.file_type,
        pack_id=req.pack_id,
        pack_name=req.pack_name,
        workspace_path=str(workspace),
    )


@router.post("/rulepacks/extract/save")
def save_extracted_rulepack_endpoint(
    req: WordRuleExtractSaveRequest,
) -> WordRulePackDetailResult:
    """Save an extracted pack; rules without provenance are rejected."""
    missing = [rule.id for rule in req.pack.rules if not (rule.source or "").strip()]
    if missing:
        raise OfficeParseError(
            "以下规则缺少来源，不能保存: " + ", ".join(missing[:10])
        )
    workspace = validate_workspace(Path(req.workspace_path))
    pack = save_rulepack(workspace, req.pack)
    return WordRulePackDetailResult(
        workspace_path=str(workspace), origin="workspace", pack=pack
    )


@router.post("/audit/revise")
def revise_word_endpoint(req: WordAuditReviseRequest) -> WordRevisionResult:
    """Write tracked replacements/comments, then re-audit (M4b)."""
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    _check_size_limit(file_path, req.max_size_bytes)
    if req.rulepack is not None:
        pack = req.rulepack
    else:
        pack = load_rulepack(workspace, req.rulepack_id or DEFAULT_RULEPACK_ID)["pack"]
    if req.changes is not None:
        raw_changes = [change.model_dump() for change in req.changes]
    else:
        audit = audit_word_document(file_path, pack, workspace_path=str(workspace))
        raw_changes = build_revision_plan(audit.issues, pack)
    if not raw_changes:
        raise OfficeParseError("没有可应用的修订")
    result = apply_word_revisions(
        file_path,
        raw_changes,
        req.output_filename,
        overwrite=req.overwrite,
        author=req.author,
        workspace_path=str(workspace),
        rule_pack_id=pack.id,
        add_comments=req.add_comments,
    )
    target = (
        file_path
        if result.overwritten
        else resolve_within(workspace, workspace / Path(result.output_path))
    )
    remaining = audit_word_document(target, pack, workspace_path=str(workspace))
    return result.model_copy(update={"remaining": remaining, "ok": remaining.ok})


@router.post("/audit/render")
def render_audit_endpoint(req: WordAuditRenderRequest) -> WordRenderAuditResult:
    """Render the DOCX to PDF and check page/margin/font/page-number (M5a)."""
    workspace = validate_workspace(Path(req.workspace_path))
    file_path = resolve_within(workspace, Path(req.file_path))
    if not file_path.is_file():
        raise OfficePathError(
            f"file_path is not a regular file: {req.file_path}",
            file_path=file_path,
        )
    _check_size_limit(file_path, req.max_size_bytes)
    return audit_word_render(
        file_path,
        workspace_path=str(workspace),
        options={
            "expected_size": req.expected_size,
            "margins_cm": req.margins_cm,
            "allowed_fonts": req.allowed_fonts,
            "require_page_number": req.require_page_number,
            "margin_tolerance_cm": req.margin_tolerance_cm,
            "page_number_band": req.page_number_band,
            "timeout_seconds": req.timeout_seconds,
        },
    )


@router.post("/audit/batch")
def batch_audit_endpoint(req: WordBatchAuditRequest) -> WordBatchAuditResult:
    """Audit multiple workspace .docx files and build a Markdown report (M5b)."""
    workspace = validate_workspace(Path(req.workspace_path))
    if req.rulepack is not None:
        pack = req.rulepack
    else:
        pack = load_rulepack(workspace, req.rulepack_id or DEFAULT_RULEPACK_ID)["pack"]
    return audit_word_batch(
        workspace,
        pack,
        file_paths=req.file_paths,
        pattern=req.pattern,
        max_files=req.max_files,
        max_size_bytes=req.max_size_bytes,
        include_report=req.include_report,
    )


__all__ = [
    "WordAuditFixRequest",
    "WordAuditRenderRequest",
    "WordAuditRequest",
    "WordAuditReviseRequest",
    "WordBatchAuditRequest",
    "WordRevisionChangeRequest",
    "WordRuleExtractRequest",
    "WordRuleExtractSaveRequest",
    "WordRulePackSaveRequest",
    "audit_word_endpoint",
    "batch_audit_endpoint",
    "delete_rulepack_endpoint",
    "extract_rulepack_endpoint",
    "fix_word_endpoint",
    "get_rulepack_endpoint",
    "list_rulepacks_endpoint",
    "render_audit_endpoint",
    "revise_word_endpoint",
    "router",
    "save_extracted_rulepack_endpoint",
    "save_rulepack_endpoint",
]
