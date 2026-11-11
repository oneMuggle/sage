"""Typed HTTP routes for the projects registry (项目模块 P1, 2026-09-13; 多形态组织增强, 2026-10-10).

"项目" = 用户在侧边栏显式登记的工作目录（对标 Cursor Recent Workspaces /
Claude Code 项目 → 会话归属）。路由面涵盖：

- ``GET  /projects``                     清单（按最近打开排序，附会话聚合）
- ``POST /projects``                     登记目录（validate_workspace 校验，幂等）
- ``DELETE /projects/{project_id}``      从清单移除（不动磁盘与会话）
- ``POST /projects/{project_id}/open``   打开项目：复用最近会话或新建并绑定
- ``POST /projects/{project_id}/sessions`` 在项目下显式新建会话并绑定目录（总是新建）
- ``GET  /projects/{project_id}/sessions`` 项目下未归档会话（新→旧）
- ``POST /projects/{project_id}/scaffold`` 按项目类型一键初始化目录结构、SAGE.md、默认约束与里程碑
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException

from backend.api.project_schemas import (
    AddMaterialFromFileRequest,
    BootstrapAppliedItem,
    BootstrapApplyRequest,
    BootstrapApplyResponse,
    BootstrapErrorModel,
    BootstrapPreviewRequest,
    BootstrapPreviewResponse,
    BootstrapScanResponse,
    BootstrapSkippedItem,
    BootstrapSuggestResponse,
    BootstrapVerification,
    ConstraintCreateRequest,
    ConstraintModel,
    ConstraintsResponse,
    ConstraintTemplateImportRequest,
    ConstraintTemplatesResponse,
    ConstraintUpdateRequest,
    CreateCheckpointRequest,
    DetectionSignalModel,
    GitCommitModel,
    GitInitResponse,
    GitStatusResponse,
    MaterialMutationResponse,
    MilestoneCreateRequest,
    MilestoneModel,
    MilestonesResponse,
    MilestoneUpdateRequest,
    ProjectAllowedPathsRequest,
    ProjectAllowedPathsResponse,
    ProjectCharterResponse,
    ProjectContextBudgetResponse,
    ProjectDiagnoseResponse,
    ProjectListResponse,
    ProjectLocationResponse,
    ProjectMaterialAddRequest,
    ProjectMaterialModel,
    ProjectMaterialsResponse,
    ProjectMaterialUpdateRequest,
    ProjectModel,
    ProjectMutationResponse,
    ProjectOpenResponse,
    ProjectRegisterRequest,
    ProjectScaffoldRequest,
    ProjectScaffoldResponse,
    ProjectSessionsResponse,
    ProjectTemplateListResponse,
    ProjectTemplateSummary,
    ProjectTreeResponse,
    ProjectTypeConfigResponse,
    ProjectTypeDetectRequest,
    ProjectTypeDetectResponse,
    ProjectUpdateRequest,
    ProjectWorkspaceOverviewResponse,
    RestoreCheckpointResponse,
    SaveAnswerRequest,
    UpdateProjectCharterRequest,
    WorkspaceCheckpointDetailResponse,
    WorkspaceCheckpointItemModel,
)
from backend.data.database import get_database, make_with_db_lock
from backend.data.project_constraint_repo import (
    CONSTRAINT_TEMPLATES,
    ProjectConstraint,
    ProjectConstraintRepository,
)
from backend.data.project_material_repo import (
    ProjectMaterial,
    ProjectMaterialContentTooLargeError,
    ProjectMaterialRepository,
)
from backend.data.project_milestone_repo import (
    MILESTONE_STATUS,
    PROJECT_STAGE_ENUM,
    ProjectMilestone,
    ProjectMilestoneRepository,
)
from backend.data.project_repo import (
    Project,
    ProjectNotFoundError,
    ProjectPathMissingError,
    ProjectRepository,
    create_project_session,
    open_project,
)
from backend.data.session_repo import MessageRepository
from backend.office.allowed_paths import default_allowed_paths
from backend.office.errors import OfficePathError
from backend.office.session_workspace import get_workspace_binding
from backend.office.storage import validate_workspace
from backend.services.default_workspace import DefaultWorkspaceResolver
from backend.services.git_integration import GitIntegration
from backend.services.project_archetype_scaffold import execute_project_scaffold
from backend.services.project_bootstrap import (
    apply_bootstrap,
    build_bootstrap_preview,
    build_bootstrap_scan,
    build_bootstrap_suggestions,
)
from backend.services.project_git_init import init_project_git
from backend.services.project_template import (
    get_built_in_templates,
    load_global_templates,
    load_project_template,
    resolve_template,
    scaffold_project as _scaffold_project,
)
from backend.services.project_type_detector import (
    DetectionResult,
    detect_project_type,
)
from backend.services.project_workspace_inspector import (
    create_project_checkpoint,
    delete_project_checkpoint,
    extract_workspace_file_as_material_content,
    get_project_checkpoint_detail,
    inspect_project_context_budget,
    inspect_project_runtime_and_hooks,
    inspect_project_workspace_overview,
    read_project_charter,
    restore_project_checkpoint,
    write_project_charter,
)
from backend.services.workspace_scanner import (
    ProjectTree,
    scan_project,
    sync_file_references_from_tree,
    sync_projects_from_tree,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


def with_db_lock(func):
    return make_with_db_lock(globals())(func)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _with_stats(project: Project, stats: Dict[str, Any]) -> ProjectModel:
    session_count, last_session_id = stats.get(project.path, (0, None))
    data = project.to_dict()
    return ProjectModel(
        **data,
        session_count=session_count,
        last_session_id=last_session_id,
    )


def _get_project_or_404(project_id: str) -> Project:
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    return project


def _scan_and_sync(
    project: Project, *, force: bool = False
) -> Tuple[Optional[ProjectTree], List[str]]:
    """扫描项目目录并把发现的子项目同步进注册表。

    嵌套关系属于派生数据：扫描失败只记日志，不影响注册/打开主流程。
    """
    root = Path(project.path)
    try:
        template = load_project_template(root)
        tree = scan_project(root, template, force=force)
        created = sync_projects_from_tree(project.id, tree)
        sync_file_references_from_tree(project.id, tree)
        return tree, created
    except Exception as exc:  # noqa: BLE001 — 扫描失败不阻断主流程
        logger.info("project scan skipped for %s: %s", root, exc)
        return None, []


def _attach_project_ids(node: Dict[str, Any], repo: ProjectRepository) -> None:
    """给扫描树节点补上已注册项目的 id（容器/未注册节点为 None）。"""
    project = None
    if node.get("role") in ("root", "project"):
        project = repo.get_project_for_workspace(node["path"])
    node["id"] = project.id if project is not None else None
    for child in node.get("children", []):
        _attach_project_ids(child, repo)


@router.get("/templates", response_model=ProjectTemplateListResponse)
def list_project_templates() -> ProjectTemplateListResponse:
    """列出可用于项目创建的模板（内置 + 用户全局库）。

    P3 (2026-11-05)：前端模板选择器消费。只返回元信息 + 目录/文件路径清单，
    不暴露 file.content 以避免响应过大。内置模板带 ``project_type`` 便于前端
    按项目类型筛选；全局模板 ``project_type=None``。
    """
    summaries: List[ProjectTemplateSummary] = []

    # ① 内置模板（按 project_type 排序，稳定顺序）
    for project_type, template in sorted(get_built_in_templates().items()):
        summaries.append(
            ProjectTemplateSummary(
                name=template.name,
                description=template.description,
                source="built_in",
                project_type=project_type,
                directory_count=len(template.directories),
                file_count=len(template.files),
                directories=[d.path for d in template.directories],
                files=[f.path for f in template.files],
            )
        )

    # ② 用户全局模板（来自 ~/.sage/templates/*.json）
    for template in load_global_templates():
        # 与内置同名时跳过，避免前端重复展示（内置优先）
        if any(s.name == template.name for s in summaries):
            continue
        summaries.append(
            ProjectTemplateSummary(
                name=template.name,
                description=template.description,
                source="global",
                project_type=None,
                directory_count=len(template.directories),
                file_count=len(template.files),
                directories=[d.path for d in template.directories],
                files=[f.path for f in template.files],
            )
        )

    return ProjectTemplateListResponse(templates=summaries)


@router.get("/{project_id}/tree", response_model=ProjectTreeResponse)
@with_db_lock
def get_project_tree(project_id: str, refresh: bool = False) -> ProjectTreeResponse:
    """返回项目目录树（含扫描发现的子项目）。

    ``refresh=true`` 强制重扫（绕过 30s 缓存），供前端手动刷新按钮使用。
    每次调用都会把扫描到的子项目幂等同步进注册表（只增不删）。
    """
    project = _get_project_or_404(project_id)
    tree, created = _scan_and_sync(project, force=refresh)
    if tree is None:
        raise _error(410, "project_path_missing", "项目目录不存在或无法读取")
    payload = tree.to_dict()
    _attach_project_ids(payload["root"], ProjectRepository())
    return ProjectTreeResponse(
        project_id=project.id,
        root=payload["root"],
        symlinks=payload["symlinks"],
        truncated=payload["truncated"],
        scanned_at=payload["scanned_at"],
        created_project_ids=created,
    )


@router.get("/{project_id}/location", response_model=ProjectLocationResponse)
@with_db_lock
def get_project_location(project_id: str) -> ProjectLocationResponse:
    """返回项目目录的规范化绝对路径（只读，不刷新 last_opened_at、不建会话）。"""
    project = _get_project_or_404(project_id)
    try:
        resolved = validate_workspace(Path(project.path))
    except OfficePathError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
    return ProjectLocationResponse(id=project.id, path=str(resolved))


@router.post(
    "/{project_id}/bootstrap/scan", response_model=BootstrapScanResponse
)
@with_db_lock
async def bootstrap_scan(project_id: str) -> BootstrapScanResponse:
    """确定性扫描项目（不调用 LLM），供初始化向导立即展示扫描结果。"""
    project = _get_project_or_404(project_id)
    data = await build_bootstrap_scan(project)
    repo = ProjectRepository()
    return BootstrapScanResponse(
        project=_with_stats(project, repo.session_stats()),
        scan=data["scan"],
    )


@router.post(
    "/{project_id}/bootstrap/suggest", response_model=BootstrapSuggestResponse
)
@with_db_lock
async def bootstrap_suggest(
    project_id: str, request: BootstrapPreviewRequest
) -> BootstrapSuggestResponse:
    """生成 AI 初始化建议（LLM 可用时），供初始化向导第二步调用。"""
    project = _get_project_or_404(project_id)
    data = await build_bootstrap_suggestions(project, use_llm=request.use_llm)
    return BootstrapSuggestResponse(
        suggestions=data["suggestions"],
        llm_available=data["llm_available"],
        llm_error=data.get("llm_error"),
        rule_source=data.get("rule_source"),
    )


@router.post(
    "/{project_id}/bootstrap/preview", response_model=BootstrapPreviewResponse
)
@with_db_lock
async def bootstrap_preview(
    project_id: str, request: BootstrapPreviewRequest
) -> BootstrapPreviewResponse:
    """扫描项目并返回 AI 初始化建议（只读）。"""
    project = _get_project_or_404(project_id)
    data = await build_bootstrap_preview(project, use_llm=request.use_llm)
    repo = ProjectRepository()
    return BootstrapPreviewResponse(
        project=_with_stats(project, repo.session_stats()),
        scan=data["scan"],
        suggestions=data["suggestions"],
        llm_available=data["llm_available"],
        llm_error=data.get("llm_error"),
        rule_source=data.get("rule_source"),
    )


@router.post(
    "/{project_id}/bootstrap/apply", response_model=BootstrapApplyResponse
)
@with_db_lock
def bootstrap_apply(
    project_id: str, request: BootstrapApplyRequest
) -> BootstrapApplyResponse:
    """应用用户确认的初始化建议（逐项幂等）。"""
    project = _get_project_or_404(project_id)
    accept = (
        request.model_dump()
        if hasattr(request, "model_dump")
        else request.dict()
    )
    result = apply_bootstrap(project, accept)
    repo = ProjectRepository()
    updated = repo.get(project_id) or project
    return BootstrapApplyResponse(
        project=_with_stats(updated, repo.session_stats()),
        applied=result["applied"],
        skipped=result["skipped"],
        errors=[BootstrapErrorModel(**item) for item in result["errors"]],
        applied_items=[
            BootstrapAppliedItem(**item) for item in result.get("applied_items", [])
        ],
        skipped_items=[
            BootstrapSkippedItem(**item) for item in result.get("skipped_items", [])
        ],
        verification=(
            BootstrapVerification(**result["verification"])
            if result.get("verification")
            else None
        ),
        git=result.get("git"),
    )


@router.post("/{project_id}/git/init", response_model=GitInitResponse)
@with_db_lock
def init_project_git_route(project_id: str) -> GitInitResponse:
    """在项目目录执行 git init（仅在用户显式请求时调用）。"""
    project = _get_project_or_404(project_id)
    result = init_project_git(project.path)
    if result.get("initialized") or result.get("already_repo"):
        ProjectRepository().update_vcs_mode(project_id, "git")
    return GitInitResponse(**result)


def _material_model(material: ProjectMaterial) -> ProjectMaterialModel:
    return ProjectMaterialModel(**material.to_dict())


def _constraint_model(constraint: ProjectConstraint) -> ConstraintModel:
    return ConstraintModel(**constraint.to_dict())


def _milestone_model(milestone: ProjectMilestone) -> MilestoneModel:
    return MilestoneModel(**milestone.to_dict())


@router.get("", response_model=ProjectListResponse)
@with_db_lock
def list_projects() -> ProjectListResponse:
    repo = ProjectRepository()
    stats = repo.session_stats()
    return ProjectListResponse(projects=[_with_stats(p, stats) for p in repo.list()])


@router.post("", response_model=ProjectModel)
@with_db_lock
def register_project(request: ProjectRegisterRequest) -> ProjectModel:
    try:
        detected_type = None
        project_type = request.project_type
        if project_type is None:
            result = detect_project_type(Path(request.path))
            detected_type = result.project_type
            project_type = detected_type

        # 未显式提供 allowed_paths（None）时预填常用文档目录，减少工作区外
        # 读写审批；显式 [] 表示用户选择清空，保持不变。
        allowed_paths = request.allowed_paths
        if allowed_paths is None:
            allowed_paths = default_allowed_paths()

        project = ProjectRepository().register(
            request.path,
            allowed_paths=allowed_paths,
            project_type=project_type,
            detected_type=detected_type,
        )
    except OfficePathError as exc:
        raise _error(400, "invalid_workspace_path", "项目路径无效或目录不存在") from exc

    # P3 (2026-11-05): 用户在创建对话框里选了模板 → 在扫描前执行脚手架，
    # 让 scanner 能看到模板生成的目录/文件（例如 SAGE.md 触发 context_file
    # 子项目发现）。scaffold 本身幂等（已存在同名条目跳过），失败不阻断
    # 注册主流程——降级为普通空项目，让 UI 后续手动触发。
    if request.template_name:
        try:
            template = resolve_template(
                project_type=project_type,
                project_root=Path(project.path),
                template_name=request.template_name,
            )
            _scaffold_project(
                template=template,
                project_root=Path(project.path),
                project_name=project.name,
            )
        except Exception as exc:  # noqa: BLE001 — scaffold 失败不阻断注册
            logger.info("project scaffold skipped for %s: %s", project.path, exc)

    # 设计 §7.4：注册时首次扫描，发现并登记子项目（失败忽略）
    _scan_and_sync(project)
    stats = ProjectRepository().session_stats()
    return _with_stats(project, stats)


@router.patch("/{project_id}", response_model=ProjectModel)
@with_db_lock
def update_project(project_id: str, request: ProjectUpdateRequest) -> ProjectModel:
    """更新项目概览字段。未出现在请求中的字段保持不变。"""
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    fields_set = getattr(request, "model_fields_set", None) or getattr(request, "__fields_set__", set())
    if "description" in fields_set:
        repo.update_description(project_id, request.description)
    if "instructions" in fields_set:
        repo.update_instructions(project_id, request.instructions)
    if "project_type" in fields_set:
        repo.update_project_type(project_id, request.project_type)
    if "project_stage" in fields_set:
        repo.update_project_stage(project_id, request.project_stage)
        # Keep playbook state/history and projected rules consistent when the
        # legacy stage selector is used.
        try:
            from backend.data.playbook_repo import PlaybookRepository
            from backend.services.playbook_actions import project_playbook_rules

            playbook_repo = PlaybookRepository()
            snapshot = playbook_repo.get_active(project_id)
            if snapshot is not None:
                state = playbook_repo.get_state(project_id)
                history = list(state.get("stage_history") or [])
                history.append(
                    {
                        "from": state.get("current_stage"),
                        "to": request.project_stage,
                        "at": int(time.time() * 1000),
                        "source": "project_update",
                    }
                )
                state["current_stage"] = request.project_stage
                state["stage_history"] = history[-100:]
                playbook_repo.update_state(project_id, state)
                if request.project_stage:
                    project_playbook_rules(
                        project_id, snapshot.spec, stage_id=request.project_stage
                    )
        except Exception:  # noqa: BLE001 — stage update must not fail on playbook sync
            logging.getLogger(__name__).warning(
                "failed to sync playbook stage for %s", project_id, exc_info=True
            )
    if "status" in fields_set:
        repo.update_status(project_id, request.status or "active")
    if "project_sub_type" in fields_set:
        repo.update_project_sub_type(project_id, request.project_sub_type)
    if "vcs_mode" in fields_set and request.vcs_mode:
        repo.update_vcs_mode(project_id, request.vcs_mode)

    updated = repo.get(project_id)
    assert updated is not None
    return _with_stats(updated, repo.session_stats())


@router.put("/{project_id}/allowed-paths", response_model=ProjectAllowedPathsResponse)
@with_db_lock
def update_project_allowed_paths(
    project_id: str, request: ProjectAllowedPathsRequest
) -> ProjectAllowedPathsResponse:
    """更新项目 allowed_paths。"""
    repo = ProjectRepository()
    _get_project_or_404(project_id)
    updated = repo.update_allowed_paths(project_id, request.allowed_paths)
    if not updated:
        raise _error(404, "project_not_found", "项目不存在")
    return ProjectAllowedPathsResponse(
        id=project_id,
        allowed_paths=request.allowed_paths,
    )


@router.get("/{project_id}/materials", response_model=ProjectMaterialsResponse)
@with_db_lock
def list_project_materials(project_id: str) -> ProjectMaterialsResponse:
    _get_project_or_404(project_id)
    materials = ProjectMaterialRepository().list_by_project(project_id)
    return ProjectMaterialsResponse(materials=[_material_model(material) for material in materials])


@router.post(
    "/{project_id}/materials",
    response_model=ProjectMaterialModel,
    status_code=201,
)
@with_db_lock
def add_project_material(
    project_id: str, request: ProjectMaterialAddRequest
) -> ProjectMaterialModel:
    _get_project_or_404(project_id)
    try:
        material = ProjectMaterialRepository().add(
            project_id=project_id,
            content=request.content,
            source_message_id=request.source_message_id,
        )
    except ProjectMaterialContentTooLargeError as exc:
        raise _error(413, "material_too_large", str(exc)) from exc
    return _material_model(material)


@router.patch(
    "/{project_id}/materials/{material_id}",
    response_model=ProjectMaterialModel,
)
@with_db_lock
def update_project_material(
    project_id: str, material_id: str, request: ProjectMaterialUpdateRequest
) -> ProjectMaterialModel:
    """切换项目资料是否参与系统提示词上下文注入 (NotebookLM 式资料源开关)。"""
    _get_project_or_404(project_id)
    materials = ProjectMaterialRepository()
    existing = materials.get(material_id)
    if existing is None or existing.project_id != project_id:
        raise _error(404, "material_not_found", "资料不存在")
    updated = materials.set_enabled(material_id, request.enabled)
    if updated is None:
        raise _error(404, "material_not_found", "资料不存在")
    return _material_model(updated)


@router.get("/{project_id}/context-budget", response_model=ProjectContextBudgetResponse)
@with_db_lock
def get_project_context_budget(project_id: str) -> ProjectContextBudgetResponse:
    """获取项目五层受控上下文水位统计。"""
    project = _get_project_or_404(project_id)
    return ProjectContextBudgetResponse(**inspect_project_context_budget(project))


@router.get("/{project_id}/workspace-overview", response_model=ProjectWorkspaceOverviewResponse)
@with_db_lock
def get_project_workspace_overview(project_id: str) -> ProjectWorkspaceOverviewResponse:
    """获取项目工作区多态资产台账（案卷文书、科研文献/实验产物、代码工程指示器）。"""
    project = _get_project_or_404(project_id)
    return ProjectWorkspaceOverviewResponse(**inspect_project_workspace_overview(project))


@router.post("/{project_id}/checkpoints", response_model=WorkspaceCheckpointItemModel, status_code=201)
@with_db_lock
def create_project_workspace_checkpoint(
    project_id: str, request: CreateCheckpointRequest
) -> WorkspaceCheckpointItemModel:
    """为内置版本控制 (builtin VCS) 项目创建手动版本快照检查点。"""
    project = _get_project_or_404(project_id)
    try:
        cp = create_project_checkpoint(project, request.label or "")
    except ValueError as exc:
        raise _error(400, "checkpoint_failed", str(exc)) from exc
    return WorkspaceCheckpointItemModel(**cp)


@router.get("/{project_id}/checkpoints/{checkpoint_id}", response_model=WorkspaceCheckpointDetailResponse)
@with_db_lock
def get_project_workspace_checkpoint(
    project_id: str, checkpoint_id: str
) -> WorkspaceCheckpointDetailResponse:
    """获取指定内置版本控制检查点的文件清单与快照预览内容。"""
    project = _get_project_or_404(project_id)
    try:
        detail = get_project_checkpoint_detail(project, checkpoint_id)
    except FileNotFoundError as exc:
        raise _error(404, "checkpoint_not_found", str(exc)) from exc
    except ValueError as exc:
        raise _error(400, "checkpoint_invalid", str(exc)) from exc
    return WorkspaceCheckpointDetailResponse(**detail)


@router.delete("/{project_id}/checkpoints/{checkpoint_id}", response_model=MaterialMutationResponse)
@with_db_lock
def delete_project_workspace_checkpoint(project_id: str, checkpoint_id: str) -> MaterialMutationResponse:
    project = _get_project_or_404(project_id)
    try:
        delete_project_checkpoint(project, checkpoint_id)
    except FileNotFoundError as exc:
        raise _error(404, "checkpoint_not_found", str(exc)) from exc
    except ValueError as exc:
        raise _error(400, "checkpoint_delete_failed", str(exc)) from exc
    return MaterialMutationResponse(removed=True)


@router.post("/{project_id}/checkpoints/{checkpoint_id}/restore", response_model=RestoreCheckpointResponse)
@with_db_lock
def restore_project_workspace_checkpoint(
    project_id: str, checkpoint_id: str
) -> RestoreCheckpointResponse:
    """将项目工作区内的文本与规范文件还原到指定内置检查点快照。"""
    project = _get_project_or_404(project_id)
    try:
        res = restore_project_checkpoint(project, checkpoint_id)
    except FileNotFoundError as exc:
        raise _error(404, "checkpoint_not_found", str(exc)) from exc
    except ValueError as exc:
        raise _error(400, "checkpoint_restore_failed", str(exc)) from exc
    return RestoreCheckpointResponse(**res)


@router.get("/{project_id}/charter", response_model=ProjectCharterResponse)
@with_db_lock
def get_project_charter(project_id: str) -> ProjectCharterResponse:
    """读取项目工作区 L1 规范文件 SAGE.md 及其形态化推荐模板。"""
    project = _get_project_or_404(project_id)
    return ProjectCharterResponse(**read_project_charter(project))


@router.put("/{project_id}/charter", response_model=ProjectCharterResponse)
@with_db_lock
def update_project_charter(
    project_id: str, body: UpdateProjectCharterRequest
) -> ProjectCharterResponse:
    """在线编辑并保存项目工作区 L1 规范文件 SAGE.md。"""
    project = _get_project_or_404(project_id)
    try:
        res = write_project_charter(project, body.content)
    except ValueError as exc:
        raise _error(400, "charter_write_failed", str(exc)) from exc
    return ProjectCharterResponse(**res)


@router.delete("/{project_id}/materials/{material_id}", response_model=MaterialMutationResponse)
@with_db_lock
def remove_project_material(project_id: str, material_id: str) -> MaterialMutationResponse:
    _get_project_or_404(project_id)
    materials = ProjectMaterialRepository()
    material = materials.get(material_id)
    if material is None or material.project_id != project_id:
        raise _error(404, "material_not_found", "资料不存在")
    if not materials.remove(material_id):
        raise _error(404, "material_not_found", "资料不存在")
    return MaterialMutationResponse(removed=True)


@router.post("/{project_id}/materials/from-file", response_model=ProjectMaterialModel, status_code=201)
@with_db_lock
def add_project_material_from_file(
    project_id: str, request: AddMaterialFromFileRequest
) -> ProjectMaterialModel:
    """将项目工作区内的文件（文献 .bib/.tex/.md/.ipynb 或案卷 .docx/.xlsx/.pptx 等）一键纳入受控资料池。"""
    project = _get_project_or_404(project_id)
    try:
        content = extract_workspace_file_as_material_content(
            Path(project.path), request.relative_path
        )
    except FileNotFoundError as exc:
        raise _error(404, "workspace_file_not_found", str(exc)) from exc
    except ValueError as exc:
        raise _error(400, "invalid_workspace_file_path", str(exc)) from exc

    material = ProjectMaterialRepository().add(
        project_id=project.id,
        content=content,
        source_message_id=None,
    )
    return _material_model(material)


@router.post("/{project_id}/materials/save-answer", response_model=ProjectMaterialModel, status_code=201)
@with_db_lock
def save_answer_as_project_material(
    project_id: str, request: SaveAnswerRequest
) -> ProjectMaterialModel:
    """把当前项目绑定会话中的可见回答保存为项目资料。"""
    project = _get_project_or_404(project_id)
    message = MessageRepository().get(request.message_id)
    if message is None:
        raise _error(404, "message_not_found", "消息不存在")
    if message.role != "assistant":
        raise _error(
            400,
            "message_role_not_savable",
            "仅可保存助手回答,用户消息不允许作为项目资料",
        )

    binding = get_workspace_binding(get_database().get_connection(), message.session_id)
    if binding is None or binding.workspace_path != project.path:
        raise _error(403, "message_project_mismatch", "消息不属于该项目")

    try:
        material = ProjectMaterialRepository().add(
            project_id=project.id,
            content=message.content,
            source_message_id=message.id,
        )
    except ProjectMaterialContentTooLargeError as exc:
        raise _error(413, "material_too_large", str(exc)) from exc
    return _material_model(material)


@router.delete("/{project_id}", response_model=ProjectMutationResponse)
@with_db_lock
def remove_project(project_id: str) -> ProjectMutationResponse:
    removed = ProjectRepository().remove(project_id)
    if not removed:
        raise _error(404, "project_not_found", "项目不存在")
    return ProjectMutationResponse(removed=True)


@router.post("/{project_id}/open", response_model=ProjectOpenResponse)
@with_db_lock
def open_project_route(project_id: str) -> ProjectOpenResponse:
    """打开项目：最近活跃会话优先，否则新建会话并绑定项目目录。

    成功打开后把项目目录写入 ``preferences``（``last_workspace_path``），
    作为后续 ``create_session`` 决策链的最高优先级输入。写入失败不阻塞主流程
    （fail-open）—— 项目能打开比"记住偏好"更重要。
    """
    try:
        project, session, created = open_project(project_id)
    except ProjectNotFoundError as exc:
        raise _error(404, "project_not_found", "项目不存在") from exc
    except ProjectPathMissingError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
    _remember_workspace_fail_open(project.path)
    # 设计 §7.4：打开时增量刷新子项目（30s 缓存内不重复扫描）
    _scan_and_sync(project)
    stats = ProjectRepository().session_stats()
    return ProjectOpenResponse(
        project=_with_stats(project, stats),
        session=session.to_dict(),
        created=created,
    )


@router.post("/{project_id}/sessions", response_model=ProjectOpenResponse, status_code=201)
@with_db_lock
def create_project_session_route(project_id: str) -> ProjectOpenResponse:
    """在项目下显式新建一个会话并绑定项目目录（总是新建，不复用）。"""
    try:
        project, session = create_project_session(project_id)
    except ProjectNotFoundError as exc:
        raise _error(404, "project_not_found", "项目不存在") from exc
    except ProjectPathMissingError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
    _remember_workspace_fail_open(project.path)
    # 设计 §7.4：新建会话时增量刷新子项目
    _scan_and_sync(project)
    stats = ProjectRepository().session_stats()
    return ProjectOpenResponse(
        project=_with_stats(project, stats),
        session=session.to_dict(),
        created=True,
    )


def _remember_workspace_fail_open(workspace_path: str) -> None:
    """Persist ``workspace_path`` as the user's remembered default.

    Fail-open: any exception (path validation, database error) is logged and
    swallowed — a broken preference write must never prevent the user from
    opening a project they explicitly chose.
    """
    try:
        DefaultWorkspaceResolver().remember_workspace(workspace_path)
    except Exception as exc:  # noqa: BLE001 — 显式目录写入失败不能阻塞打开流程
        logger.warning(
            "project_routes: remember_workspace failed (fail-open)",
            extra={"path": workspace_path, "reason": str(exc)},
        )


@router.get("/{project_id}/sessions", response_model=ProjectSessionsResponse)
@with_db_lock
def list_project_sessions(project_id: str) -> ProjectSessionsResponse:
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    sessions = repo.sessions_for_project(project.path)
    return ProjectSessionsResponse(sessions=[s.to_dict() for s in sessions])


@router.post("/detect-type", response_model=ProjectTypeDetectResponse)
def detect_project_type_route(request: ProjectTypeDetectRequest) -> ProjectTypeDetectResponse:
    """预览项目类型检测结果（不注册项目）。"""
    try:
        path = Path(request.path).expanduser().resolve()
        if not path.is_dir():
            raise _error(400, "path_not_directory", "路径不存在或不是目录")
        result: DetectionResult = detect_project_type(path)
        return ProjectTypeDetectResponse(
            project_type=result.project_type,
            confidence=result.confidence,
            signals=[DetectionSignalModel(type=s.type, weight=s.weight) for s in result.signals],
            sub_type=result.sub_type,
            tech_stack=list(result.tech_stack),
        )
    except OSError as exc:
        raise _error(400, "path_error", f"路径错误: {exc}") from exc


@router.post("/{project_id}/scaffold", response_model=ProjectScaffoldResponse)
@with_db_lock
def scaffold_project_route(
    project_id: str, request: ProjectScaffoldRequest
) -> ProjectScaffoldResponse:
    """按项目形态一键初始化标准子目录、SAGE.md、预设约束与阶段里程碑。"""
    repo = ProjectRepository()
    project = _get_project_or_404(project_id)
    if not Path(project.path).is_dir():
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动")
    res = execute_project_scaffold(
        project,
        project_type=request.project_type,
        create_directories=request.create_directories,
        create_sage_md=request.create_sage_md,
        import_default_constraints=request.import_default_constraints,
        seed_default_milestones=request.seed_default_milestones,
    )
    updated_project = _get_project_or_404(project_id)
    return ProjectScaffoldResponse(
        project=_with_stats(updated_project, repo.session_stats()),
        **res,
    )


# ── Project constraints routes (2026-09-24) ──────────────────────────────────


@router.get("/templates/constraints", response_model=ConstraintTemplatesResponse)
def list_constraint_templates() -> ConstraintTemplatesResponse:
    """列出可用的约束模板。"""
    return ConstraintTemplatesResponse(templates=dict(CONSTRAINT_TEMPLATES.items()))


@router.get("/{project_id}/constraints", response_model=ConstraintsResponse)
@with_db_lock
def list_constraints(project_id: str) -> ConstraintsResponse:
    """列出项目的所有约束。"""
    _get_project_or_404(project_id)
    constraints = ProjectConstraintRepository().list_by_project(project_id)
    return ConstraintsResponse(constraints=[_constraint_model(c) for c in constraints])


@router.post(
    "/{project_id}/constraints",
    response_model=ConstraintModel,
    status_code=201,
)
@with_db_lock
def create_constraint(project_id: str, request: ConstraintCreateRequest) -> ConstraintModel:
    """创建一条项目约束。"""
    _get_project_or_404(project_id)
    constraint = ProjectConstraintRepository().create(
        project_id=project_id,
        category=request.category,
        content=request.content,
        trigger_pattern=request.trigger_pattern,
        priority=request.priority,
    )
    return _constraint_model(constraint)


@router.patch("/{project_id}/constraints/{constraint_id}", response_model=ConstraintModel)
@with_db_lock
def update_constraint(
    project_id: str, constraint_id: str, request: ConstraintUpdateRequest
) -> ConstraintModel:
    """更新约束字段。"""
    _get_project_or_404(project_id)
    repo = ProjectConstraintRepository()
    constraint = repo.get(constraint_id)
    if constraint is None or constraint.project_id != project_id:
        raise _error(404, "constraint_not_found", "约束不存在")

    fields_set = getattr(request, "model_fields_set", None) or getattr(request, "__fields_set__", set())
    updated = repo.update(
        constraint_id,
        category=request.category if "category" in fields_set else None,
        content=request.content if "content" in fields_set else None,
        trigger_pattern=request.trigger_pattern if "trigger_pattern" in fields_set else None,
        priority=request.priority if "priority" in fields_set else None,
        enabled=request.enabled if "enabled" in fields_set else None,
    )
    if not updated:
        raise _error(404, "constraint_not_found", "约束不存在")
    return _constraint_model(repo.get(constraint_id))


@router.delete("/{project_id}/constraints/{constraint_id}", response_model=MaterialMutationResponse)
@with_db_lock
def delete_constraint(project_id: str, constraint_id: str) -> MaterialMutationResponse:
    """删除约束。"""
    _get_project_or_404(project_id)
    repo = ProjectConstraintRepository()
    constraint = repo.get(constraint_id)
    if constraint is None or constraint.project_id != project_id:
        raise _error(404, "constraint_not_found", "约束不存在")
    repo.delete(constraint_id)
    return MaterialMutationResponse(removed=True)


@router.post("/{project_id}/constraints/import-template", response_model=ConstraintsResponse, status_code=201)
@with_db_lock
def import_constraint_template(
    project_id: str, request: ConstraintTemplateImportRequest
) -> ConstraintsResponse:
    """从预设模板导入约束。"""
    _get_project_or_404(project_id)
    repo = ProjectConstraintRepository()
    try:
        created = repo.import_template(project_id, request.template)
    except ValueError as exc:
        raise _error(400, "unknown_template", str(exc)) from exc
    return ConstraintsResponse(constraints=[_constraint_model(c) for c in created])


# ── Project milestones routes (2026-09-24) ───────────────────────────────────


@router.get("/{project_id}/milestones", response_model=MilestonesResponse)
@with_db_lock
def list_milestones(project_id: str, status: Optional[str] = None) -> MilestonesResponse:
    """列出项目的所有里程碑。可按状态过滤。"""
    _get_project_or_404(project_id)
    milestones = ProjectMilestoneRepository().list_by_project(project_id, status=status)
    return MilestonesResponse(milestones=[_milestone_model(m) for m in milestones])


@router.post("/{project_id}/milestones", response_model=MilestoneModel, status_code=201)
@with_db_lock
def create_milestone(project_id: str, request: MilestoneCreateRequest) -> MilestoneModel:
    """创建一个里程碑。"""
    _get_project_or_404(project_id)
    milestone = ProjectMilestoneRepository().create(
        project_id=project_id,
        title=request.title,
        description=request.description,
        stage=request.stage,
        due_date=request.due_date,
        sort_order=request.sort_order,
    )
    return _milestone_model(milestone)


@router.patch("/{project_id}/milestones/{milestone_id}", response_model=MilestoneModel)
@with_db_lock
def update_milestone(
    project_id: str, milestone_id: str, request: MilestoneUpdateRequest
) -> MilestoneModel:
    """更新里程碑字段。"""
    _get_project_or_404(project_id)
    repo = ProjectMilestoneRepository()
    milestone = repo.get(milestone_id)
    if milestone is None or milestone.project_id != project_id:
        raise _error(404, "milestone_not_found", "里程碑不存在")

    fields_set = getattr(request, "model_fields_set", None) or getattr(request, "__fields_set__", set())
    try:
        updated = repo.update(
            milestone_id,
            title=request.title if "title" in fields_set else None,
            description=request.description if "description" in fields_set else None,
            stage=request.stage if "stage" in fields_set else None,
            due_date=request.due_date if "due_date" in fields_set else None,
            status=request.status if "status" in fields_set else None,
            sort_order=request.sort_order if "sort_order" in fields_set else None,
        )
    except ValueError as exc:
        raise _error(400, "invalid_status", str(exc)) from exc
    if not updated:
        raise _error(404, "milestone_not_found", "里程碑不存在")
    return _constraint_or_milestone_get(repo, milestone_id)


def _constraint_or_milestone_get(repo: ProjectMilestoneRepository, milestone_id: str) -> MilestoneModel:
    row = repo.get(milestone_id)
    assert row is not None
    return _milestone_model(row)


@router.post("/{project_id}/milestones/{milestone_id}/complete", response_model=MilestoneModel)
@with_db_lock
def complete_milestone(project_id: str, milestone_id: str) -> MilestoneModel:
    """标记里程碑为已完成。"""
    _get_project_or_404(project_id)
    repo = ProjectMilestoneRepository()
    milestone = repo.get(milestone_id)
    if milestone is None or milestone.project_id != project_id:
        raise _error(404, "milestone_not_found", "里程碑不存在")
    repo.mark_completed(milestone_id)
    return _constraint_or_milestone_get(repo, milestone_id)


@router.delete("/{project_id}/milestones/{milestone_id}", response_model=MaterialMutationResponse)
@with_db_lock
def delete_milestone(project_id: str, milestone_id: str) -> MaterialMutationResponse:
    """删除里程碑。"""
    _get_project_or_404(project_id)
    repo = ProjectMilestoneRepository()
    milestone = repo.get(milestone_id)
    if milestone is None or milestone.project_id != project_id:
        raise _error(404, "milestone_not_found", "里程碑不存在")
    repo.delete(milestone_id)
    return MaterialMutationResponse(removed=True)


@router.get("/config/types", response_model=ProjectTypeConfigResponse)
def get_project_type_config() -> ProjectTypeConfigResponse:
    """获取项目类型配置（阶段枚举、约束模板列表）。"""
    return ProjectTypeConfigResponse(
        stage_enum=PROJECT_STAGE_ENUM,
        milestone_status=MILESTONE_STATUS,
        constraint_templates=list(CONSTRAINT_TEMPLATES.keys()),
    )


@router.get("/{project_id}/git-status", response_model=GitStatusResponse)
def get_project_git_status(project_id: str) -> GitStatusResponse:
    """获取项目 Git 仓库状态（分支、未提交变更、最近提交）。"""
    project = _get_project_or_404(project_id)

    git = GitIntegration(project.path)
    if not git.is_git_repo():
        return GitStatusResponse(is_repo=False)

    status = git.get_status()
    commits = git.get_log(limit=5)

    return GitStatusResponse(
        is_repo=True,
        current_branch=status.current_branch,
        modified_files=status.modified_files,
        staged_files=status.staged_files,
        untracked_files=status.untracked_files,
        recent_commits=[
            GitCommitModel(sha=c.sha, author=c.author, date=c.date, message=c.message)
            for c in commits
        ],
    )


@router.get("/{project_id}/diagnose", response_model=ProjectDiagnoseResponse)
def get_project_diagnose(project_id: str) -> ProjectDiagnoseResponse:
    """获取项目本地运行环境满足度、测试命令入口与 Hooks 信任状态。"""
    project = _get_project_or_404(project_id)
    data = inspect_project_runtime_and_hooks(project.id, project.path)
    return ProjectDiagnoseResponse(**data)



# ── AI 治理分析路由 (2026-10-27) ─────────────────────────────────────────────


from backend.api.project_schemas import (
    AnalysisReportModel,
    CodebaseProfileModel,
    ProjectAnalyzeRequest,
    ProjectAnalyzeResponse,
    ProjectProfileResponse,
    RuleGenerationRequest,
    RuleGenerationResultModel,
    SubTypesResponse,
)
from backend.services.project_analysis_agent import (
    AnalysisReport,
    DocRef,
    ProjectAnalysisAgent,
    SuggestedRule,
)
from backend.services.project_profiler import (
    CodebaseProfile,
    GitStats,
    SourceSample,
    profile_project,
)
from backend.services.project_rule_generator import ProjectRuleGenerator
from backend.services.project_subtypes import sub_types_payload


def _profile_from_dict(d: Dict[str, Any]) -> CodebaseProfile:
    """把前端传回的 profile dict 反序列化为数据类。"""
    samples = [
        SourceSample(
            path=str(s.get("path", "")),
            language=str(s.get("language", "")),
            lines=int(s.get("lines", 0)),
            content="",
        )
        for s in (d.get("source_samples") or [])
    ]
    gs = d.get("git_stats") or {}
    return CodebaseProfile(
        root=str(d.get("root", "")),
        level1_type=d.get("level1_type"),
        sub_type=d.get("sub_type"),
        tech_stack=list(d.get("tech_stack") or []),
        frameworks=list(d.get("frameworks") or []),
        build_commands=list(d.get("build_commands") or []),
        test_frameworks=list(d.get("test_frameworks") or []),
        lint_configs=list(d.get("lint_configs") or []),
        ci_workflows=list(d.get("ci_workflows") or []),
        existing_rule_files=list(d.get("existing_rule_files") or []),
        directory_layout=list(d.get("directory_layout") or []),
        source_samples=samples,
        git_stats=GitStats(
            is_repo=bool(gs.get("is_repo", False)),
            current_branch=gs.get("current_branch"),
            commit_count=int(gs.get("commit_count", 0) or 0),
            recent_commit_count=int(gs.get("recent_commit_count", 0) or 0),
            branch_count=int(gs.get("branch_count", 0) or 0),
            last_commit_at=gs.get("last_commit_at"),
            dirty_files=int(gs.get("dirty_files", 0) or 0),
        ),
        vcs_mode=str(d.get("vcs_mode", "unknown")),
    )


def _report_from_dict(d: Dict[str, Any]) -> AnalysisReport:
    """把前端传回的 report dict 反序列化为数据类。"""
    rules = [
        SuggestedRule(
            template_key=str(r.get("template_key", "")),
            label=str(r.get("label", "")),
            reason=str(r.get("reason", "")),
            confidence=float(r.get("confidence", 0.0) or 0.0),
            category=str(r.get("category", "coding_style") or "coding_style"),
            content=str(r.get("content", "")),
            trigger_pattern=str(r.get("trigger_pattern", "always") or "always"),
            priority=int(r.get("priority", 5) or 5),
        )
        for r in (d.get("suggested_rules") or [])
    ]
    refs = [
        DocRef(
            title=str(ref.get("title", "")),
            reason=str(ref.get("reason", "")),
            path=str(ref.get("path", "")),
        )
        for ref in (d.get("docs_refs") or [])
    ]
    return AnalysisReport(
        level1_type=str(d.get("level1_type", "coding")),
        sub_type=d.get("sub_type"),
        confidence=float(d.get("confidence", 0.0) or 0.0),
        tech_stack=list(d.get("tech_stack") or []),
        architecture_summary=str(d.get("architecture_summary", "")),
        suggested_rules=rules,
        governance_recommendations=list(d.get("governance_recommendations") or []),
        stage_recommendation=d.get("stage_recommendation"),
        sage_md_draft=str(d.get("sage_md_draft", "")),
        docs_refs=refs,
        llm_available=bool(d.get("llm_available", True)),
    )


@router.get("/sub-types", response_model=SubTypesResponse)
def list_sub_types() -> SubTypesResponse:
    """返回所有 L1 -> L2 子类型定义（供前端渲染两级选择器）。"""
    payload = sub_types_payload()
    return SubTypesResponse(
        level1_types=list(payload["level1_types"]),
        sub_types=payload["sub_types"],
    )


@router.post("/profile", response_model=ProjectProfileResponse)
def collect_project_profile(request: ProjectAnalyzeRequest) -> ProjectProfileResponse:
    """仅采集确定性画像（不调 LLM，供调试/快速预览）。"""
    try:
        path = Path(request.path).expanduser().resolve()
        if not path.is_dir():
            raise _error(400, "path_not_directory", "路径不存在或不是目录")
    except OSError as exc:
        raise _error(400, "path_error", f"路径错误: {exc}") from exc
    profile = profile_project(path)
    return ProjectProfileResponse(
        profile=CodebaseProfileModel(**profile.to_dict(include_source_content=False))
    )


# 项目分析缓存：cache_key -> (timestamp, profile_dict, report_dict)
# cache_key = path + git_sha，TTL = 1 小时
_analysis_cache: Dict[str, Tuple[float, Dict[str, Any], Dict[str, Any]]] = {}
_ANALYSIS_CACHE_TTL = 3600  # 1 小时
_ANALYSIS_CACHE_MAX_SIZE = 50  # 最多缓存 50 个项目


def _get_git_sha(path: Path) -> Optional[str]:
    """获取目录的 git commit sha（非 git 仓库返回 None）"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None


def _get_cache_key(path: Path) -> Optional[str]:
    """计算缓存 key = path + git_sha，非 git 仓库返回 None（不缓存）"""
    git_sha = _get_git_sha(path)
    if git_sha is None:
        return None
    return f"{path}:{git_sha}"


def _cleanup_cache() -> None:
    """清理过期缓存，保持缓存大小在限制内"""
    now = time.time()
    # 删除过期条目
    expired = [k for k, (ts, _, _) in _analysis_cache.items() if now - ts > _ANALYSIS_CACHE_TTL]
    for k in expired:
        del _analysis_cache[k]
    # 如果还超限，删除最旧的
    if len(_analysis_cache) > _ANALYSIS_CACHE_MAX_SIZE:
        sorted_items = sorted(_analysis_cache.items(), key=lambda x: x[1][0])
        to_remove = len(_analysis_cache) - _ANALYSIS_CACHE_MAX_SIZE
        for k, _ in sorted_items[:to_remove]:
            del _analysis_cache[k]


@router.post("/analyze", response_model=ProjectAnalyzeResponse)
async def analyze_project(request: ProjectAnalyzeRequest) -> ProjectAnalyzeResponse:
    """采集画像 + LLM 深度分析 → 治理报告。LLM 缺失时返回确定性降级版本（200）。

    缓存策略（2026-11-11）：相同 path + git_sha 在 1 小时内直接返回缓存结果，
    避免重复分析。非 git 仓库不缓存。
    """
    try:
        path = Path(request.path).expanduser().resolve()
        if not path.is_dir():
            raise _error(400, "path_not_directory", "路径不存在或不是目录")
    except OSError as exc:
        raise _error(400, "path_error", f"路径错误: {exc}") from exc

    # 检查缓存（仅 git 仓库）
    cache_key = _get_cache_key(path)
    if cache_key and cache_key in _analysis_cache:
        ts, profile_dict, report_dict = _analysis_cache[cache_key]
        if time.time() - ts < _ANALYSIS_CACHE_TTL:
            return ProjectAnalyzeResponse(
                profile=CodebaseProfileModel(**profile_dict),
                report=AnalysisReportModel(**report_dict),
            )

    # 将同步的 profile_project 放入线程池，避免阻塞事件循环
    loop = asyncio.get_event_loop()
    profile = await loop.run_in_executor(None, lambda: profile_project(path))

    agent = ProjectAnalysisAgent()
    # 整体 3 分钟超时（LLM 分析 + 画像采集）
    async with asyncio.timeout(180):
        report = await agent.analyze(profile)

    profile_dict = profile.to_dict(include_source_content=False)
    report_dict = report.to_dict()

    # 存入缓存
    if cache_key:
        _analysis_cache[cache_key] = (time.time(), profile_dict, report_dict)
        _cleanup_cache()

    return ProjectAnalyzeResponse(
        profile=CodebaseProfileModel(**profile_dict),
        report=AnalysisReportModel(**report_dict),
    )


@router.post("/generate-rules", response_model=RuleGenerationResultModel)
async def generate_rules_from_report(
    request: RuleGenerationRequest,
) -> RuleGenerationResultModel:
    """基于已确认的分析报告生成约束草稿（含里程碑推荐）。"""
    try:
        profile = _profile_from_dict(request.profile)
        report = _report_from_dict(request.report)
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(400, "invalid_payload", f"请求体字段缺失或类型错误: {exc}") from exc

    existing_contents: Optional[List[str]] = None
    if request.project_id:
        project = ProjectRepository().get(request.project_id)
        if project is not None:
            existing_contents = [
                c.content for c in ProjectConstraintRepository().list_by_project(request.project_id)
            ]

    try:
        generator = ProjectRuleGenerator()
        result = await generator.generate(profile, report, existing_contents)
    except Exception as exc:
        logger.warning("ProjectRuleGenerator 构造失败: %s", exc)
        return RuleGenerationResultModel(
            rules=[],
            milestones=[],
            llm_available=False,
            skipped_duplicates=0,
        )
    return RuleGenerationResultModel(**result.to_dict())


__all__ = ["router"]
