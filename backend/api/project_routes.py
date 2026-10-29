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

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from backend.api.project_schemas import (
    AddMaterialFromFileRequest,
    ConstraintCreateRequest,
    ConstraintModel,
    ConstraintsResponse,
    ConstraintTemplateImportRequest,
    ConstraintTemplatesResponse,
    ConstraintUpdateRequest,
    CreateCheckpointRequest,
    DetectionSignalModel,
    GitCommitModel,
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
from backend.office.errors import OfficePathError
from backend.office.session_workspace import get_workspace_binding
from backend.services.default_workspace import DefaultWorkspaceResolver
from backend.services.git_integration import GitIntegration
from backend.services.project_archetype_scaffold import execute_project_scaffold
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

        project = ProjectRepository().register(
            request.path,
            allowed_paths=request.allowed_paths,
            project_type=project_type,
            detected_type=detected_type,
        )
    except OfficePathError as exc:
        raise _error(400, "invalid_workspace_path", "项目路径无效或目录不存在") from exc
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


@router.post("/analyze", response_model=ProjectAnalyzeResponse)
async def analyze_project(request: ProjectAnalyzeRequest) -> ProjectAnalyzeResponse:
    """采集画像 + LLM 深度分析 → 治理报告。LLM 缺失时返回确定性降级版本（200）。"""
    try:
        path = Path(request.path).expanduser().resolve()
        if not path.is_dir():
            raise _error(400, "path_not_directory", "路径不存在或不是目录")
    except OSError as exc:
        raise _error(400, "path_error", f"路径错误: {exc}") from exc

    profile = profile_project(path)
    agent = ProjectAnalysisAgent()
    report = await agent.analyze(profile)

    profile_dict = profile.to_dict(include_source_content=False)
    report_dict = report.to_dict()
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
