# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""Rules-management API routes (Office AI Workbench P3).

CRUD for rule groups and rules, plus AI-assisted rule extraction from a
.docx specification. Mounted under ``/api/v1/rules`` by ``backend/main.py``.

All payloads are snake_case on the wire; the frontend converts to camelCase
in ``ruleMapping.ts`` (``rulePackSerialization.ts`` consumes it for
``.sage-rules`` files).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.compat.win7.pydantic_compat import ConfigDict, field_validator
from backend.data.database import Database, get_database
from backend.office.errors import OfficePathError, OfficeSizeLimitError
from backend.office.path_safety import resolve_within
from backend.office.rule_conflicts import detect_conflicts
from backend.office.rule_executor import run_audit
from backend.office.rule_models import AuditResult, Rule, RuleGroup, RulePack, _check_pattern
from backend.office.rule_pack_io import build_rule_pack, import_rule_pack
from backend.office.rule_repo import (
    create_group,
    create_rule,
    delete_group,
    delete_rule,
    get_group,
    get_rule,
    list_groups,
    update_group,
    update_rule,
)
from backend.office.storage import validate_workspace
from backend.office.word_rule_extract import extract_word_rules_async
from backend.office.word_rulepack_models import WordRuleSpec
from backend.orchestration.llm_factory import build_llm_client_from_settings

router = APIRouter(prefix="/rules", tags=["office"])

_MAX_AUDIT_RULES = 50
_MAX_EXPORT_GROUPS = 100

_CATEGORY_TO_TYPE = {
    "page": "format",
    "style": "format",
    "structure": "structure",
    "content": "custom",
    "table": "format",
}

_CATEGORY_TO_SCOPE = {
    "page": "full",
    "style": "body",
    "structure": "heading",
    "content": "body",
    "table": "table",
}


def _db() -> Database:
    """Return the shared global Database instance (same pattern as office_routes)."""
    return get_database()


def _not_found(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _resolve_source(workspace_path: str, file_path: str, max_size_bytes: int) -> Tuple[Path, Path]:
    """Resolve the workspace + file path and enforce the size cap."""
    workspace = validate_workspace(Path(workspace_path))
    source = resolve_within(workspace, Path(file_path))
    if not source.is_file():
        raise OfficePathError(f"file_path is not a regular file: {file_path}", file_path=source)
    actual_size = source.stat().st_size
    if actual_size > max_size_bytes:
        raise OfficeSizeLimitError(
            actual_size=actual_size, max_size=max_size_bytes, file_path=source
        )
    return workspace, source


class GroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    priority: int = 0


class GroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    priority: Optional[int] = None


class RuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., pattern="^(format|terminology|citation|structure|custom)$")
    severity: str = Field(..., pattern="^(error|warning|info)$")
    scope: str = Field(..., pattern="^(full|heading|body|table|caption)$")
    description: str = ""
    check_mode: str = Field(..., pattern="^(regex|ai)$")
    pattern: Optional[str] = None
    ai_prompt: Optional[str] = None
    enabled: bool = True

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, value: Optional[str]) -> Optional[str]:
        return _check_pattern(value)


class RuleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    type: Optional[str] = Field(
        default=None, pattern="^(format|terminology|citation|structure|custom)$"
    )
    severity: Optional[str] = Field(default=None, pattern="^(error|warning|info)$")
    scope: Optional[str] = Field(default=None, pattern="^(full|heading|body|table|caption)$")
    description: Optional[str] = None
    check_mode: Optional[str] = Field(default=None, pattern="^(regex|ai)$")
    pattern: Optional[str] = None
    ai_prompt: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, value: Optional[str]) -> Optional[str]:
        return _check_pattern(value)


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    file_type: str = Field(default="spec", pattern="^(spec|template)$")
    use_llm: bool = False
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)


class ExtractWarning(BaseModel):
    code: str
    message: str


class ExtractResponse(BaseModel):
    rules: List[Rule]
    warnings: List[ExtractWarning]


class DeleteResponse(BaseModel):
    deleted: bool
    id: str


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    file_path: str
    rule_ids: List[str]
    max_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=200 * 1024 * 1024)


def _spec_to_rule(spec: WordRuleSpec) -> Rule:
    """Map an extraction spec onto the editor's Rule shape.

    Extracted rules are always AI-checked: the deterministic extractor
    describes *what* to check, not a ready-to-run regex. ``group_id`` is
    empty until the user adds the rule to a group.
    """
    category = str(spec.category)
    detail = spec.description or spec.fix_hint or spec.title
    params = ", ".join(f"{key}={value}" for key, value in sorted(spec.params.items()))
    prompt = f"检查文档是否满足规则「{spec.title}」：{detail}"
    if params:
        prompt = f"{prompt}（判定参数：{params}）"
    return Rule(
        id=f"rule-{uuid.uuid4().hex[:8]}",
        name=spec.title,
        type=_CATEGORY_TO_TYPE.get(category, "custom"),
        severity=spec.severity,
        scope=_CATEGORY_TO_SCOPE.get(category, "body"),
        description=spec.description,
        check_mode="ai",
        pattern=None,
        ai_prompt=prompt,
        enabled=True,
        group_id="",
    )


@router.get("/groups", response_model=List[RuleGroup])
def list_groups_endpoint() -> List[RuleGroup]:
    return list_groups(_db().get_connection())


@router.post("/groups", response_model=RuleGroup, status_code=status.HTTP_201_CREATED)
def create_group_endpoint(req: GroupCreateRequest) -> RuleGroup:
    return create_group(
        _db().get_connection(),
        name=req.name,
        description=req.description,
        priority=req.priority,
    )


@router.put("/groups/{group_id}", response_model=RuleGroup)
def update_group_endpoint(group_id: str, req: GroupUpdateRequest) -> RuleGroup:
    try:
        return update_group(
            _db().get_connection(),
            group_id,
            name=req.name,
            description=req.description,
            priority=req.priority,
        )
    except ValueError as exc:
        raise _not_found(exc) from exc


@router.delete("/groups/{group_id}", response_model=DeleteResponse)
def delete_group_endpoint(group_id: str) -> DeleteResponse:
    conn = _db().get_connection()
    try:
        get_group(conn, group_id)
    except ValueError as exc:
        raise _not_found(exc) from exc
    delete_group(conn, group_id)
    return DeleteResponse(deleted=True, id=group_id)


@router.post("/groups/{group_id}/rules", response_model=Rule, status_code=status.HTTP_201_CREATED)
def create_rule_endpoint(group_id: str, req: RuleCreateRequest) -> Rule:
    conn = _db().get_connection()
    try:
        get_group(conn, group_id)
    except ValueError as exc:
        raise _not_found(exc) from exc
    return create_rule(
        conn,
        group_id=group_id,
        name=req.name,
        type=req.type,
        severity=req.severity,
        scope=req.scope,
        check_mode=req.check_mode,
        description=req.description,
        pattern=req.pattern,
        ai_prompt=req.ai_prompt,
        enabled=req.enabled,
    )


@router.put("/rules/{rule_id}", response_model=Rule)
def update_rule_endpoint(rule_id: str, req: RuleUpdateRequest) -> Rule:
    payload = req.model_dump(exclude_unset=True)
    for field_name in (
        "name",
        "type",
        "severity",
        "scope",
        "check_mode",
        "description",
        "enabled",
    ):
        if field_name in payload and payload[field_name] is None:
            raise HTTPException(status_code=422, detail=f"{field_name} cannot be null")
    try:
        return update_rule(_db().get_connection(), rule_id, **payload)
    except ValueError as exc:
        raise _not_found(exc) from exc


@router.delete("/rules/{rule_id}", response_model=DeleteResponse)
def delete_rule_endpoint(rule_id: str) -> DeleteResponse:
    conn = _db().get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM office_rules WHERE id = ?", (rule_id,))
    if cursor.fetchone() is None:
        raise HTTPException(status_code=404, detail=f"Rule not found: {rule_id}")
    delete_rule(conn, rule_id)
    return DeleteResponse(deleted=True, id=rule_id)


@router.post("/extract", response_model=ExtractResponse)
async def extract_endpoint(req: ExtractRequest) -> ExtractResponse:
    workspace, source = _resolve_source(req.workspace_path, req.file_path, req.max_size_bytes)
    result = await extract_word_rules_async(
        source,
        file_type=req.file_type,
        workspace_path=str(workspace),
        use_llm=req.use_llm,
    )
    return ExtractResponse(
        rules=[_spec_to_rule(spec) for spec in result.pack.rules],
        warnings=[
            ExtractWarning(code=item["code"], message=item["message"]) for item in result.warnings
        ],
    )


@router.post("/audit", response_model=AuditResult)
async def audit_endpoint(req: AuditRequest) -> AuditResult:
    conn = _db().get_connection()
    rule_ids = list(dict.fromkeys(req.rule_ids))
    if not rule_ids:
        raise HTTPException(status_code=422, detail="rule_ids cannot be empty")
    if len(rule_ids) > _MAX_AUDIT_RULES:
        raise HTTPException(
            status_code=422,
            detail=f"rule_ids cannot exceed {_MAX_AUDIT_RULES}",
        )
    rules: List[Rule] = []
    for rule_id in rule_ids:
        try:
            rules.append(get_rule(conn, rule_id))
        except ValueError as exc:
            raise _not_found(exc) from exc

    workspace, source = _resolve_source(req.workspace_path, req.file_path, req.max_size_bytes)

    llm_client = None
    if any(rule.enabled and rule.check_mode == "ai" for rule in rules):
        llm_client = build_llm_client_from_settings()
        if llm_client is None:
            raise HTTPException(status_code=503, detail="LLM 客户端未配置")

    return await run_audit(rules, source, workspace_path=str(workspace), llm_client=llm_client)


class ConflictCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_ids: List[str]


class ConflictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_ids: List[str]
    message: str
    suggestion: str
    severity: str


class ConflictListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflicts: List[ConflictModel]


@router.post("/check-conflicts", response_model=ConflictListResponse)
def check_conflicts_endpoint(req: ConflictCheckRequest) -> ConflictListResponse:
    conn = _db().get_connection()
    rule_ids = list(dict.fromkeys(req.rule_ids))
    if len(rule_ids) < 2:
        raise HTTPException(status_code=422, detail="rule_ids requires at least 2 distinct ids")
    if len(rule_ids) > _MAX_AUDIT_RULES:
        raise HTTPException(
            status_code=422,
            detail=f"rule_ids cannot exceed {_MAX_AUDIT_RULES}",
        )
    rules: List[Rule] = []
    for rule_id in rule_ids:
        try:
            rules.append(get_rule(conn, rule_id))
        except ValueError as exc:
            raise _not_found(exc) from exc
    conflicts = detect_conflicts(rules)
    return ConflictListResponse(conflicts=[ConflictModel(**asdict(c)) for c in conflicts])


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: List[str]
    name: str = Field(..., min_length=1)
    version: str = "1.0"


class ImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: int
    imported_rules: int


@router.post("/export", response_model=RulePack)
async def export_endpoint(req: ExportRequest) -> RulePack:
    conn = _db().get_connection()
    # Dedupe group_ids preserving first-seen order.
    deduped_ids = list(dict.fromkeys(req.group_ids))
    if not deduped_ids:
        raise HTTPException(422, "group_ids cannot be empty")
    if len(deduped_ids) > _MAX_EXPORT_GROUPS:
        raise HTTPException(
            status_code=422,
            detail=f"group_ids cannot exceed {_MAX_EXPORT_GROUPS}",
        )
    try:
        return build_rule_pack(conn, deduped_ids, name=req.name, version=req.version)
    except ValueError as exc:
        raise _not_found(exc) from exc


@router.post("/import", response_model=ImportResponse)
async def import_endpoint(pack: RulePack) -> ImportResponse:
    report = import_rule_pack(_db().get_connection(), pack)
    return ImportResponse(groups=report.groups, imported_rules=report.imported_rules)
