"""HTTP routes for project playbooks (2026-10-31).

Mounted under ``/api/v1``:

- ``GET  /playbooks/builtin``
- ``GET  /playbooks/builtin/{playbook_id}``
- ``GET  /projects/{project_id}/playbook``
- ``PUT  /projects/{project_id}/playbook``
- ``GET  /projects/{project_id}/playbook/audit``
- ``POST /projects/{project_id}/playbook/stage/confirm``
- ``POST /projects/{project_id}/playbook/actions/apply``
- ``GET  /projects/{project_id}/playbook/export``
- ``POST /playbooks/import/preview``
- ``POST /playbooks/import``
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from backend.api.playbook_schemas import (
    BuiltinPlaybookListResponse,
    BuiltinPlaybookResponse,
    PlaybookActionsApplyRequest,
    PlaybookActionsApplyResponse,
    PlaybookAiAuditRequest,
    PlaybookAuditResponse,
    PlaybookAuthorPreviewRequest,
    PlaybookAuthorPreviewResponse,
    PlaybookBindRequest,
    PlaybookCurrentResponse,
    PlaybookExportResponse,
    PlaybookImportPreviewRequest,
    PlaybookImportPreviewResponse,
    PlaybookImportRequest,
    PlaybookStageConfirmRequest,
    PlaybookWikiExportResponse,
)
from backend.data.database import make_with_db_lock
from backend.data.playbook_repo import PlaybookRepository, PlaybookSnapshot
from backend.data.project_repo import Project, ProjectRepository
from backend.services.playbook_actions import apply_playbook_actions
from backend.services.playbook_ai import audit_with_llm
from backend.services.playbook_auditor import audit_playbook
from backend.services.playbook_author import build_author_preview
from backend.services.playbook_library import (
    build_export_envelope,
    get_builtin,
    list_builtin,
    render_agents_markdown,
    render_markdown_handbook,
    suggested_builtin,
    validate_import_envelope,
)
from backend.services.playbook_spec import (
    PlaybookValidationError,
    normalize_playbook,
    spec_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["playbooks"])


def with_db_lock(func):  # noqa: ANN001 — 与 project_routes 相同的装饰器工厂
    return make_with_db_lock(globals())(func)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _project_or_404(project_id: str) -> Project:
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    if not Path(project.path).is_dir():
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动")
    return project


def _ensure_state(project_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    repo = PlaybookRepository()
    state = repo.get_state(project_id)
    stage_ids = [stage["id"] for stage in spec.get("stages") or []]
    if state.get("current_stage") not in stage_ids:
        state["current_stage"] = stage_ids[0] if stage_ids else None
    if not isinstance(state.get("stage_history"), list):
        state["stage_history"] = []
    if not isinstance(state.get("waivers"), list):
        state["waivers"] = []
    if not isinstance(state.get("manual_done"), list):
        state["manual_done"] = []
    repo.update_state(project_id, state)
    return state


def _current_payload(project: Project) -> PlaybookCurrentResponse:
    repo = PlaybookRepository()
    snapshot = repo.get_active(project.id)
    state = repo.get_state(project.id)
    suggested = suggested_builtin(project.project_type or project.detected_type)
    payload = PlaybookCurrentResponse(
        bound=snapshot is not None,
        state=state,
        suggested=suggested,
    )
    if snapshot is not None:
        payload.playbook = snapshot.spec
        payload.source = snapshot.source
        payload.version = snapshot.version
        payload.spec_hash = snapshot.spec_hash
        payload.audit = audit_playbook(project, snapshot.spec, state=state)
    return payload


def _active_snapshot_or_404(project_id: str) -> PlaybookSnapshot:
    snapshot = PlaybookRepository().get_active(project_id)
    if snapshot is None:
        raise _error(404, "playbook_not_bound", "项目尚未绑定规程")
    return snapshot


def _diff_specs(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    old_stages = {stage["id"]: stage for stage in old.get("stages") or []}
    new_stages = {stage["id"]: stage for stage in new.get("stages") or []}
    old_dirs = {item["path"] for item in old.get("directory_layout") or []}
    new_dirs = {item["path"] for item in new.get("directory_layout") or []}
    return {
        "stages_added": sorted(set(new_stages) - set(old_stages)),
        "stages_removed": sorted(set(old_stages) - set(new_stages)),
        "stages_changed": sorted(
            stage_id
            for stage_id in set(old_stages) & set(new_stages)
            if old_stages[stage_id] != new_stages[stage_id]
        ),
        "directories_added": sorted(new_dirs - old_dirs),
        "directories_removed": sorted(old_dirs - new_dirs),
        "name_changed": old.get("name") != new.get("name"),
        "description_changed": old.get("description") != new.get("description"),
    }


def _merge_specs(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Merge imported spec into the active one: new entries win, old-only kept."""
    old_by_id = {stage["id"]: stage for stage in old.get("stages") or []}
    new_by_id = {stage["id"]: stage for stage in new.get("stages") or []}
    merged_stages = dict(old_by_id)
    merged_stages.update(new_by_id)
    directories: Dict[str, Dict[str, Any]] = {
        item["path"]: item for item in old.get("directory_layout") or []
    }
    directories.update(
        {item["path"]: item for item in new.get("directory_layout") or []}
    )
    merged = dict(new)
    merged["stages"] = sorted(
        merged_stages.values(), key=lambda stage: (stage.get("order", 0), stage["id"])
    )
    merged["directory_layout"] = list(directories.values())
    merged["global_rules"] = list(old.get("global_rules") or [])
    for rule in new.get("global_rules") or []:
        if rule not in merged["global_rules"]:
            merged["global_rules"].append(rule)
    return normalize_playbook(merged)


@router.get("/playbooks/builtin", response_model=BuiltinPlaybookListResponse)
def list_builtin_playbooks() -> BuiltinPlaybookListResponse:
    return BuiltinPlaybookListResponse(playbooks=list_builtin())


@router.get("/playbooks/builtin/{playbook_id}", response_model=BuiltinPlaybookResponse)
def get_builtin_playbook(playbook_id: str) -> BuiltinPlaybookResponse:
    spec = get_builtin(playbook_id)
    if spec is None:
        raise _error(404, "playbook_not_found", "内置规程不存在")
    return BuiltinPlaybookResponse(playbook=spec)


@router.get(
    "/projects/{project_id}/playbook", response_model=PlaybookCurrentResponse
)
@with_db_lock
def get_project_playbook(project_id: str) -> PlaybookCurrentResponse:
    project = _project_or_404(project_id)
    return _current_payload(project)


@router.put(
    "/projects/{project_id}/playbook", response_model=PlaybookCurrentResponse
)
@with_db_lock
def bind_project_playbook(
    project_id: str, request: PlaybookBindRequest
) -> PlaybookCurrentResponse:
    project = _project_or_404(project_id)
    if bool(request.playbook_id) == bool(request.spec):
        raise _error(400, "invalid_playbook_request", "playbook_id 与 spec 必须二选一")
    if request.playbook_id:
        spec = get_builtin(request.playbook_id)
        if spec is None:
            raise _error(404, "playbook_not_found", "内置规程不存在")
        source = request.source or (f"builtin:{request.playbook_id}")
    else:
        try:
            spec = normalize_playbook(request.spec or {})
        except PlaybookValidationError as exc:
            raise _error(400, "invalid_playbook", str(exc)) from exc
        source = request.source or "custom"
    PlaybookRepository().create_snapshot(project.id, spec, source=source)
    _ensure_state(project.id, spec)
    return _current_payload(project)


@router.get(
    "/projects/{project_id}/playbook/audit", response_model=PlaybookAuditResponse
)
@with_db_lock
def audit_project_playbook(project_id: str) -> PlaybookAuditResponse:
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    state = PlaybookRepository().get_state(project.id)
    return PlaybookAuditResponse(**audit_playbook(project, snapshot.spec, state=state))


@router.post(
    "/projects/{project_id}/playbook/audit/ai",
    response_model=PlaybookAuditResponse,
)
@with_db_lock
async def audit_project_playbook_with_ai(
    project_id: str, request: PlaybookAiAuditRequest
) -> PlaybookAuditResponse:
    """Deterministic audit plus optional LLM content checks / stage adjudication."""
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    state = PlaybookRepository().get_state(project.id)
    result = await audit_with_llm(
        project,
        snapshot.spec,
        state=state,
        use_llm=request.use_llm,
    )
    return PlaybookAuditResponse(
        **result.audit,
        llm_available=result.llm_available,
    )


@router.post(
    "/projects/{project_id}/playbook/author/preview",
    response_model=PlaybookAuthorPreviewResponse,
)
@with_db_lock
async def author_project_playbook(
    project_id: str, request: PlaybookAuthorPreviewRequest
) -> PlaybookAuthorPreviewResponse:
    """Generate an AI-assisted playbook draft (deterministic fallback)."""
    project = _project_or_404(project_id)
    result = await build_author_preview(
        project, request.answers, use_llm=request.use_llm
    )
    return PlaybookAuthorPreviewResponse(**result.to_dict())


@router.post(
    "/projects/{project_id}/playbook/stage/confirm",
    response_model=PlaybookCurrentResponse,
)
@with_db_lock
def confirm_project_stage(
    project_id: str, request: PlaybookStageConfirmRequest
) -> PlaybookCurrentResponse:
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    stage_ids = [stage["id"] for stage in snapshot.spec.get("stages") or []]
    if request.stage_id not in stage_ids:
        raise _error(400, "unknown_stage", "阶段不存在于当前规程")
    result = apply_playbook_actions(
        project, [{"type": "set_stage", "payload": {"stage_id": request.stage_id}}]
    )
    if result["errors"]:
        raise _error(400, "stage_confirm_failed", result["errors"][0]["message"])
    refreshed = _project_or_404(project_id)
    return _current_payload(refreshed)


@router.post(
    "/projects/{project_id}/playbook/actions/apply",
    response_model=PlaybookActionsApplyResponse,
)
@with_db_lock
def apply_project_playbook_actions(
    project_id: str, request: PlaybookActionsApplyRequest
) -> PlaybookActionsApplyResponse:
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    result = apply_playbook_actions(project, request.actions)
    state = PlaybookRepository().get_state(project.id)
    return PlaybookActionsApplyResponse(
        applied=result["applied"],
        skipped=result["skipped"],
        errors=result["errors"],
        checkpoint_created=result["checkpoint_created"],
        audit=audit_playbook(project, snapshot.spec, state=state),
    )


@router.get(
    "/projects/{project_id}/playbook/export", response_model=PlaybookExportResponse
)
@with_db_lock
def export_project_playbook(
    project_id: str,
    format: str = Query(default="json", pattern="^(json|md|agents)$"),
    include_scaffold: bool = Query(default=True),
) -> PlaybookExportResponse:
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    spec = snapshot.spec
    if format == "md":
        return PlaybookExportResponse(
            format="md",
            filename="{}-handbook.md".format(spec["id"]),
            content=render_markdown_handbook(spec),
        )
    if format == "agents":
        return PlaybookExportResponse(
            format="agents",
            filename="{}-AGENTS.md".format(spec["id"]),
            content=render_agents_markdown(spec),
        )
    return PlaybookExportResponse(
        format="json",
        filename="{}.sageplaybook.json".format(spec["id"]),
        content=build_export_envelope(
            spec, include_scaffold=include_scaffold, app_version="unknown"
        ),
    )


@router.post(
    "/projects/{project_id}/playbook/wiki/export",
    response_model=PlaybookWikiExportResponse,
)
@with_db_lock
def export_project_playbook_to_wiki(project_id: str) -> PlaybookWikiExportResponse:
    """Write the playbook handbook into the project Wiki (sage-owned page only)."""
    from backend.wiki.files import secure_ensure_directory, secure_write_file

    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    root = Path(project.path)
    relative = "wiki/guides/playbook-handbook.md"
    target = root / relative
    created = not target.exists()
    if not created:
        try:
            existing = target.read_text(encoding="utf-8", errors="ignore")[:1000]
        except OSError as exc:
            raise _error(500, "wiki_read_failed", str(exc)) from exc
        if "generator: sage" not in existing:
            raise _error(
                409,
                "wiki_page_exists",
                "目标 Wiki 页面已存在且不是 Sage 生成，请先改名或删除",
            )
    content = "---\ngenerator: sage\n---\n\n" + render_markdown_handbook(snapshot.spec)
    try:
        secure_ensure_directory(root, target.parent)
        secure_write_file(root, target, content)
    except Exception as exc:  # noqa: BLE001 — surface wiki write failure
        raise _error(500, "wiki_write_failed", str(exc)) from exc
    return PlaybookWikiExportResponse(
        path=relative, created=created, updated=not created
    )


@router.post(
    "/playbooks/import/preview", response_model=PlaybookImportPreviewResponse
)
def preview_playbook_import(
    request: PlaybookImportPreviewRequest,
) -> PlaybookImportPreviewResponse:
    try:
        parsed = validate_import_envelope(request.envelope)
    except PlaybookValidationError as exc:
        raise _error(400, "invalid_playbook", str(exc)) from exc
    diff: Dict[str, Any] = {}
    if request.project_id:
        project = _project_or_404(request.project_id)
        active = PlaybookRepository().get_active(project.id)
        if active is not None:
            diff = _diff_specs(active.spec, parsed["playbook"])
    return PlaybookImportPreviewResponse(
        playbook=parsed["playbook"], scaffold=parsed["scaffold"], diff=diff
    )


@router.post("/playbooks/import", response_model=PlaybookCurrentResponse)
@with_db_lock
def import_playbook(request: PlaybookImportRequest) -> PlaybookCurrentResponse:
    try:
        parsed = validate_import_envelope(request.envelope)
    except PlaybookValidationError as exc:
        raise _error(400, "invalid_playbook", str(exc)) from exc
    if not request.project_id:
        raise _error(400, "project_id_required", "导入后需要指定绑定项目")
    project = _project_or_404(request.project_id)
    repo = PlaybookRepository()
    active = repo.get_active(project.id)
    spec = parsed["playbook"]
    if active is not None and request.conflict == "merge":
        spec = _merge_specs(active.spec, spec)
    if (
        active is not None
        and request.conflict == "save_as_new"
        and active.spec.get("id") == spec["id"]
    ):
        duplicate = dict(spec)
        duplicate["id"] = "{}-imported-{}".format(spec["id"], spec_hash(spec)[:8])
        spec = normalize_playbook(duplicate)
    source = f"imported:{spec_hash(spec)[:12]}"
    repo.create_snapshot(project.id, spec, source=source)
    _ensure_state(project.id, spec)
    return _current_payload(project)


__all__ = ["router"]
