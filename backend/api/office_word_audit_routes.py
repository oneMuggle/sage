"""Word rule pack + deterministic audit routes (M2a)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from backend.office.errors import OfficeParseError, OfficePathError, OfficeSizeLimitError
from backend.office.path_safety import resolve_within
from backend.office.storage import validate_workspace
from backend.office.word_audit import audit_word_document
from backend.office.word_fix import fix_word_document
from backend.office.word_rule_extract import extract_word_rules
from backend.office.word_rulepack_models import (
    WordAuditFixResult,
    WordAuditResult,
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
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024)


class WordRuleExtractSaveRequest(BaseModel):
    """POST /office/word/rulepacks/extract/save body."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    pack: WordRulePack


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


__all__ = [
    "WordAuditFixRequest",
    "WordAuditRequest",
    "WordRuleExtractRequest",
    "WordRuleExtractSaveRequest",
    "WordRulePackSaveRequest",
    "audit_word_endpoint",
    "delete_rulepack_endpoint",
    "extract_rulepack_endpoint",
    "fix_word_endpoint",
    "get_rulepack_endpoint",
    "list_rulepacks_endpoint",
    "router",
    "save_extracted_rulepack_endpoint",
    "save_rulepack_endpoint",
]
