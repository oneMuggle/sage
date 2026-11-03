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

import base64
import contextlib
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    PlaybookDocumentImportRequest,
    PlaybookDocumentImportResponse,
    PlaybookEventAggregateResponse,
    PlaybookEventModel,
    PlaybookEventsResponse,
    PlaybookExportResponse,
    PlaybookImportPreviewRequest,
    PlaybookImportPreviewResponse,
    PlaybookImportRequest,
    PlaybookLibraryDetailResponse,
    PlaybookLibraryItemModel,
    PlaybookLibraryResponse,
    PlaybookLibrarySaveRequest,
    PlaybookLibrarySaveResponse,
    PlaybookRuleCleanupResponse,
    PlaybookSharedResponse,
    PlaybookShareRequest,
    PlaybookShareResponse,
    PlaybookStageConfirmRequest,
    PlaybookStateUpdateRequest,
    PlaybookVersionModel,
    PlaybookVersionsResponse,
    PlaybookWikiExportResponse,
)
from backend.data.database import make_with_db_lock
from backend.data.playbook_event_repo import (
    PlaybookEventRepository,
    record_playbook_event,
)
from backend.data.playbook_library_repo import PlaybookLibraryRepository
from backend.data.playbook_repo import PlaybookRepository, PlaybookSnapshot
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_repo import Project, ProjectRepository
from backend.services.playbook_actions import apply_playbook_actions, project_playbook_rules
from backend.services.playbook_ai import audit_with_llm
from backend.services.playbook_auditor import audit_playbook
from backend.services.playbook_author import build_author_preview
from backend.services.playbook_diff import diff_playbooks
from backend.services.playbook_document_import import import_playbook_from_document
from backend.services.playbook_library import (
    build_export_envelope,
    get_builtin,
    list_builtin,
    render_agents_markdown,
    render_markdown_handbook,
    suggested_builtin,
    validate_import_envelope,
)
from backend.services.playbook_share import (
    PlaybookNotFoundError,
    ShareTokenExpiredError,
    ShareTokenInvalidError,
    create_share_link,
    resolve_share_token,
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


def _create_bind_checkpoint(project: Project) -> None:
    try:
        from backend.services.project_workspace_inspector import create_project_checkpoint

        create_project_checkpoint(project, "绑定项目规程")
    except Exception:  # noqa: BLE001 — checkpoint failure must not block binding
        logger.warning("failed to create checkpoint before playbook bind", exc_info=True)


def _validate_state_keys(
    spec: Dict[str, Any],
    waivers: Optional[List[str]],
    manual_done: Optional[List[str]],
) -> None:
    artifact_keys = set()
    criterion_keys = set()
    for stage in spec.get("stages") or []:
        for artifact in stage.get("artifacts") or []:
            artifact_keys.add(f"{stage.get('id')}.{artifact.get('id')}")
        for criterion in stage.get("exit_criteria") or []:
            criterion_keys.add(f"{stage.get('id')}.{criterion.get('id')}")
    invalid = [key for key in (waivers or []) if key not in artifact_keys]
    if invalid:
        raise _error(400, "invalid_waiver", f"未知的豁免项: {', '.join(invalid)}")
    invalid = [key for key in (manual_done or []) if key not in criterion_keys]
    if invalid:
        raise _error(
            400, "invalid_manual_done", f"未知的手动完成项: {', '.join(invalid)}"
        )


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


@router.get("/playbooks/library", response_model=PlaybookLibraryResponse)
@with_db_lock
def list_playbook_library() -> PlaybookLibraryResponse:
    items = PlaybookLibraryRepository().list()
    return PlaybookLibraryResponse(
        items=[PlaybookLibraryItemModel(**item.summary()) for item in items]
    )


@router.post("/playbooks/library", response_model=PlaybookLibrarySaveResponse)
@with_db_lock
def save_playbook_to_library(
    request: PlaybookLibrarySaveRequest,
) -> PlaybookLibrarySaveResponse:
    try:
        parsed = validate_import_envelope(request.envelope)
    except PlaybookValidationError as exc:
        raise _error(400, "invalid_playbook", str(exc)) from exc
    item, created = PlaybookLibraryRepository().save(
        parsed["playbook"], source=request.source or "imported"
    )
    # Library operations are not project-bound; use the library id as the
    # pseudo project_id so the event stays queryable.
    record_playbook_event(
        f"library:{item.id}",
        "library_save",
        payload={
            "library_id": item.id,
            "name": item.name,
            "created": created,
        },
    )
    return PlaybookLibrarySaveResponse(
        item=PlaybookLibraryItemModel(**item.summary()),
        created=created,
    )


@router.get(
    "/playbooks/library/{library_id}", response_model=PlaybookLibraryDetailResponse
)
@with_db_lock
def get_playbook_library_item(library_id: str) -> PlaybookLibraryDetailResponse:
    item = PlaybookLibraryRepository().get(library_id)
    if item is None:
        raise _error(404, "playbook_not_found", "规程库条目不存在")
    return PlaybookLibraryDetailResponse(
        item=PlaybookLibraryItemModel(**item.summary()),
        playbook=item.spec,
    )


@router.get(
    "/playbooks/library/{library_id}/export", response_model=PlaybookExportResponse
)
@with_db_lock
def export_playbook_library_item(
    library_id: str,
    include_scaffold: bool = Query(default=True),
) -> PlaybookExportResponse:
    item = PlaybookLibraryRepository().get(library_id)
    if item is None:
        raise _error(404, "playbook_not_found", "规程库条目不存在")
    spec = item.spec
    record_playbook_event(
        f"library:{item.id}",
        "library_export",
        payload={"library_id": item.id, "name": item.name},
    )
    return PlaybookExportResponse(
        format="json",
        filename="{}.sageplaybook.json".format(spec.get("id") or item.id),
        content=build_export_envelope(
            spec, include_scaffold=include_scaffold, app_version="unknown"
        ),
    )


@router.delete("/playbooks/library/{library_id}")
@with_db_lock
def delete_playbook_from_library(library_id: str) -> Dict[str, bool]:
    removed = PlaybookLibraryRepository().delete(library_id)
    if removed:
        record_playbook_event(
            f"library:{library_id}",
            "library_delete",
            payload={"library_id": library_id},
        )
    if not removed:
        raise _error(404, "playbook_not_found", "规程库条目不存在")
    return {"removed": True}


@router.post(
    "/playbooks/library/{library_id}/share", response_model=PlaybookShareResponse
)
@with_db_lock
def create_playbook_share_link(
    library_id: str,
    request: Optional[PlaybookShareRequest] = None,
) -> PlaybookShareResponse:
    """生成规程分享链接（带 token，默认 7 天有效）。"""
    expiry_days = request.expiry_days if request else 7
    try:
        result = create_share_link(library_id, expiry_days=expiry_days)
    except PlaybookNotFoundError as exc:
        raise _error(404, "playbook_not_found", str(exc)) from exc

    record_playbook_event(
        f"library:{library_id}",
        "library_share",
        payload={
            "library_id": library_id,
            "expires_at": result.expires_at,
        },
    )
    return PlaybookShareResponse(
        token=result.token,
        playbook_id=result.playbook_id,
        playbook_name=result.playbook_name,
        expires_at=result.expires_at,
        share_url=result.share_url,
    )


@router.get("/playbooks/shared/{token}", response_model=PlaybookSharedResponse)
@with_db_lock
def get_shared_playbook(token: str) -> PlaybookSharedResponse:
    """通过分享 token 获取规程内容（只读）。"""
    try:
        payload = resolve_share_token(token)
    except ShareTokenExpiredError as exc:
        raise _error(410, "share_expired", str(exc)) from exc
    except ShareTokenInvalidError as exc:
        raise _error(404, "share_invalid", str(exc)) from exc
    except PlaybookNotFoundError as exc:
        raise _error(404, "playbook_not_found", str(exc)) from exc

    return PlaybookSharedResponse(**payload)


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
    selected = [bool(request.playbook_id), bool(request.library_id), bool(request.spec)]
    if sum(selected) != 1:
        raise _error(
            400,
            "invalid_playbook_request",
            "playbook_id / library_id / spec 必须三选一",
        )
    if request.library_id:
        item = PlaybookLibraryRepository().get(request.library_id)
        if item is None:
            raise _error(404, "playbook_not_found", "规程库条目不存在")
        spec = item.spec
        source = request.source or f"library:{item.id}"
    elif request.playbook_id:
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
    _create_bind_checkpoint(project)
    PlaybookRepository().create_snapshot(project.id, spec, source=source)
    state = _ensure_state(project.id, spec)
    project_playbook_rules(
        project.id, spec, stage_id=state.get("current_stage")
    )
    record_playbook_event(
        project.id,
        "bind",
        stage=state.get("current_stage"),
        payload={
            "source": source,
            "playbook_id": request.playbook_id,
            "library_id": request.library_id,
            "playbook_name": (spec.get("name") or "")[:120],
        },
    )
    return _current_payload(project)


@router.patch(
    "/projects/{project_id}/playbook/state", response_model=PlaybookCurrentResponse
)
@with_db_lock
def update_project_playbook_state(
    project_id: str, request: PlaybookStateUpdateRequest
) -> PlaybookCurrentResponse:
    """Update waivers / manual completion / conditional flags."""
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    _validate_state_keys(snapshot.spec, request.waivers, request.manual_done)
    repo = PlaybookRepository()
    state = repo.get_state(project.id)
    if request.waivers is not None:
        state["waivers"] = sorted(set(request.waivers))
    if request.manual_done is not None:
        state["manual_done"] = sorted(set(request.manual_done))
    if request.conditions is not None:
        state["conditions"] = dict(request.conditions)
    repo.update_state(project.id, state)
    state_event = (
        "exemption_grant"
        if request.waivers
        else ("manual_complete" if request.manual_done else "update_state")
    )
    record_playbook_event(
        project.id,
        state_event,
        stage=state.get("current_stage"),
        payload={
            "waivers_count": len(state.get("waivers") or []),
            "manual_done_count": len(state.get("manual_done") or []),
        },
    )
    return _current_payload(project)


@router.delete(
    "/projects/{project_id}/playbook", response_model=PlaybookCurrentResponse
)
@with_db_lock
def unbind_project_playbook(project_id: str) -> PlaybookCurrentResponse:
    """Deactivate the bound playbook and clear its state (history is kept)."""
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    playbook_name = ""
    source = ""
    if snapshot is not None:
        playbook_name = (snapshot.spec.get("name") or "")[:120]
        source = snapshot.source or ""
    PlaybookRepository().unbind(project.id)
    ProjectRepository().update_playbook_state(project.id, None)
    record_playbook_event(
        project.id,
        "unbind",
        payload={"playbook_name": playbook_name, "source": source},
    )
    return _current_payload(project)


@router.get(
    "/projects/{project_id}/playbook/versions",
    response_model=PlaybookVersionsResponse,
)
@with_db_lock
def list_project_playbook_versions(project_id: str) -> PlaybookVersionsResponse:
    project = _project_or_404(project_id)
    versions = PlaybookRepository().list_versions(project.id)
    return PlaybookVersionsResponse(
        versions=[
            PlaybookVersionModel(
                version=item.version,
                source=item.source,
                spec_hash=item.spec_hash,
                created_at=item.created_at,
                active=item.active,
            )
            for item in versions
        ]
    )


@router.post(
    "/projects/{project_id}/playbook/rules/cleanup",
    response_model=PlaybookRuleCleanupResponse,
)
@with_db_lock
def cleanup_project_playbook_rules(project_id: str) -> PlaybookRuleCleanupResponse:
    project = _project_or_404(project_id)
    removed = ProjectConstraintRepository().delete_by_source_prefix(
        project.id, "playbook:"
    )
    record_playbook_event(project.id, "cleanup_rules", payload={"removed": removed})
    return PlaybookRuleCleanupResponse(removed=removed)


@router.get(
    "/projects/{project_id}/playbook/audit", response_model=PlaybookAuditResponse
)
@with_db_lock
def audit_project_playbook(project_id: str) -> PlaybookAuditResponse:
    project = _project_or_404(project_id)
    snapshot = _active_snapshot_or_404(project.id)
    state = PlaybookRepository().get_state(project.id)
    audit = audit_playbook(project, snapshot.spec, state=state)
    record_playbook_event(
        project.id,
        "audit",
        stage=audit.get("current_stage"),
        payload={
            "issues_count": int(audit.get("overall", {}).get("issues_count") or 0),
            "unclassified_count": len(audit.get("unclassified_files") or []),
        },
    )
    return PlaybookAuditResponse(**audit)


@router.post(
    "/projects/{project_id}/playbook/audit/ai",
    response_model=PlaybookAuditResponse,
)
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
    record_playbook_event(
        project.id,
        "audit_ai",
        stage=result.audit.get("current_stage"),
        payload={
            "llm_available": bool(result.llm_available),
            "use_llm": bool(request.use_llm),
            "issues_count": int(
                result.audit.get("overall", {}).get("issues_count") or 0
            ),
        },
    )
    return PlaybookAuditResponse(
        **result.audit,
        llm_available=result.llm_available,
    )


@router.post(
    "/projects/{project_id}/playbook/author/preview",
    response_model=PlaybookAuthorPreviewResponse,
)
async def author_project_playbook(
    project_id: str, request: PlaybookAuthorPreviewRequest
) -> PlaybookAuthorPreviewResponse:
    """Generate an AI-assisted playbook draft (deterministic fallback)."""
    project = _project_or_404(project_id)
    result = await build_author_preview(
        project, request.answers, use_llm=request.use_llm
    )
    record_playbook_event(
        project.id,
        "author",
        payload={
            "llm_available": bool(result.llm_available),
            "use_llm": bool(request.use_llm),
            "source": str(result.source or "")[:120],
        },
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
    project_playbook_rules(project.id, snapshot.spec, stage_id=request.stage_id)
    record_playbook_event(
        project.id,
        "stage_confirm",
        stage=request.stage_id,
        payload={"stage_id": request.stage_id},
    )
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
    action_types = [str(a.get("type")) for a in request.actions if a.get("type")]
    # Classify as batch_move / undo_batch_move when those are the sole action.
    if action_types == ["batch_move"]:
        event_name = "batch_move"
    elif action_types == ["undo_last_batch_move"]:
        event_name = "undo_batch_move"
    else:
        event_name = "actions_apply"
    record_playbook_event(
        project.id,
        event_name,
        stage=state.get("current_stage"),
        payload={
            "action_types": action_types[:32],
            "applied": result["applied"],
            "skipped": result["skipped"],
            "errors_count": len(result["errors"]),
        },
    )
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
        record_playbook_event(project.id, "export_md", payload={"format": "md"})
        return PlaybookExportResponse(
            format="md",
            filename="{}-handbook.md".format(spec["id"]),
            content=render_markdown_handbook(spec),
        )
    if format == "agents":
        record_playbook_event(
            project.id, "export_agents", payload={"format": "agents"}
        )
        return PlaybookExportResponse(
            format="agents",
            filename="{}-AGENTS.md".format(spec["id"]),
            content=render_agents_markdown(spec),
        )
    record_playbook_event(
        project.id,
        "export_json",
        payload={"format": "json", "include_scaffold": include_scaffold},
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
    record_playbook_event(
        project.id,
        "export_wiki",
        payload={"path": relative, "created": created},
    )
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
            diff = diff_playbooks(active.spec, parsed["playbook"])
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
    if request.save_to_library:
        PlaybookLibraryRepository().save(spec, source="imported")
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
    _create_bind_checkpoint(project)
    repo.create_snapshot(project.id, spec, source=source)
    state = _ensure_state(project.id, spec)
    project_playbook_rules(
        project.id, spec, stage_id=state.get("current_stage")
    )
    record_playbook_event(
        project.id,
        "import",
        stage=state.get("current_stage"),
        payload={
            "playbook_id": spec.get("id"),
            "playbook_name": (spec.get("name") or "")[:120],
            "conflict": request.conflict,
            "saved_to_library": bool(request.save_to_library),
        },
    )
    return _current_payload(project)


@router.post(
    "/playbooks/import/document",
    response_model=PlaybookDocumentImportResponse,
)
async def import_playbook_from_document_endpoint(
    request: PlaybookDocumentImportRequest,
) -> PlaybookDocumentImportResponse:
    """从 Word/PDF/Markdown 文档生成 Playbook 预览（不写库）。

    前端上传 base64 编码的文档内容，后端解析后使用 LLM 生成
    Playbook 草案。LLM 不可用时自动降级到确定性模板。
    """
    if request.project_id:
        _project_or_404(request.project_id)

    try:
        file_bytes = base64.b64decode(request.content_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="base64 解码失败") from exc

    if not file_bytes:
        raise HTTPException(status_code=400, detail="文档内容为空")

    ext = Path(request.filename).suffix.lower()
    allowed = {".docx", ".pdf", ".md", ".pptx", ".xlsx", ".html", ".txt"}
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式：{ext}，支持 {', '.join(sorted(allowed))}",
        )

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = Path(tmp.name)

    try:
        result = await import_playbook_from_document(
            tmp_path,
            request.filename,
            use_llm=request.use_llm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("document import failed", exc_info=True)
        raise HTTPException(status_code=500, detail="文档解析失败") from exc
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()

    return PlaybookDocumentImportResponse(**result.to_dict())


@router.get(
    "/projects/{project_id}/playbook/events",
    response_model=PlaybookEventsResponse,
)
def list_playbook_events(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> PlaybookEventsResponse:
    """Return recent playbook usage events for a project (newest first)."""
    _project_or_404(project_id)
    repo = PlaybookEventRepository()
    events = repo.list_recent(project_id, limit=limit)
    return PlaybookEventsResponse(
        project_id=project_id,
        events=[
            PlaybookEventModel(
                id=e.id,
                project_id=e.project_id,
                event=e.event,
                stage=e.stage,
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in events
        ],
    )


@router.get(
    "/playbooks/events/aggregate",
    response_model=PlaybookEventAggregateResponse,
)
def aggregate_playbook_events(
    project_id: Optional[str] = Query(default=None, max_length=128),
    days: int = Query(default=30, ge=1, le=365),
) -> PlaybookEventAggregateResponse:
    """Return event counts grouped by event name within the time window."""
    repo = PlaybookEventRepository()
    counts = repo.aggregate(project_id=project_id, days=days)
    return PlaybookEventAggregateResponse(
        days=days,
        project_id=project_id,
        counts=counts,
        total=sum(counts.values()),
    )


__all__ = ["router"]
