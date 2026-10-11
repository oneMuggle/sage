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
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from backend.api.project_schemas import (
    AddMaterialFromFileRequest,
    ConstraintCreateRequest,
    ConstraintModel,
    ConstraintsResponse,
    ConstraintTemplateImportRequest,
    ConstraintTemplatesResponse,
    ConstraintUpdateRequest,
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
    SaveAnswerRequest,
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
from backend.services.git_integration import GitIntegration
from backend.services.project_archetype_scaffold import scaffold_project_archetype
from backend.services.project_type_detector import (
    DetectionResult,
    detect_project_type,
)
from backend.services.project_workspace_inspector import (
    extract_workspace_file_as_material_content,
    inspect_project_context_budget,
    inspect_project_runtime_and_hooks,
    inspect_project_workspace_overview,
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


@router.get(
    "/{project_id}/context-budget",
    response_model=ProjectContextBudgetResponse,
)
@with_db_lock
def get_project_context_budget(project_id: str) -> ProjectContextBudgetResponse:
    """获取项目五层受控上下文水位统计。"""
    project = _get_project_or_404(project_id)
    return ProjectContextBudgetResponse(**inspect_project_context_budget(project))


@router.get(
    "/{project_id}/workspace-overview",
    response_model=ProjectWorkspaceOverviewResponse,
)
@with_db_lock
def get_project_workspace_overview(project_id: str) -> ProjectWorkspaceOverviewResponse:
    """获取项目工作区多态资产台账（案卷文书、科研文献/实验产物、代码工程指示器）。"""
    project = _get_project_or_404(project_id)
    return ProjectWorkspaceOverviewResponse(**inspect_project_workspace_overview(project))


@router.delete(
    "/{project_id}/materials/{material_id}",
    response_model=MaterialMutationResponse,
)
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


@router.post(
    "/{project_id}/materials/from-file",
    response_model=ProjectMaterialModel,
    status_code=201,
)
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


@router.post(
    "/{project_id}/materials/save-answer",
    response_model=ProjectMaterialModel,
    status_code=201,
)
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
    """打开项目：最近活跃会话优先，否则新建会话并绑定项目目录。"""
    try:
        project, session, created = open_project(project_id)
    except ProjectNotFoundError as exc:
        raise _error(404, "project_not_found", "项目不存在") from exc
    except ProjectPathMissingError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
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
    stats = ProjectRepository().session_stats()
    return ProjectOpenResponse(
        project=_with_stats(project, stats),
        session=session.to_dict(),
        created=True,
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
        )
    except OSError as exc:
        raise _error(400, "path_error", f"路径错误: {exc}") from exc


@router.post("/{project_id}/scaffold", response_model=ProjectScaffoldResponse)
@with_db_lock
def scaffold_project_route(
    project_id: str, request: ProjectScaffoldRequest
) -> ProjectScaffoldResponse:
    """按项目形态（代码工程/一般档案/科研课题/个人空间）一键初始化标准子目录、SAGE.md、预设约束与阶段里程碑。"""
    repo = ProjectRepository()
    project = _get_project_or_404(project_id)
    ws_path = Path(project.path)
    if not ws_path.is_dir():
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动")

    effective_type = request.project_type or project.project_type or project.detected_type or "business"
    if request.project_type and request.project_type != project.project_type:
        repo.update_project_type(project_id, request.project_type)

    scaffold_result = scaffold_project_archetype(
        ws_path,
        effective_type,
        project_name=project.name,
        create_directories=request.create_directories,
        create_sage_md=request.create_sage_md,
    )

    imported_constraints_count = 0
    if request.import_default_constraints and effective_type in CONSTRAINT_TEMPLATES:
        c_repo = ProjectConstraintRepository()
        if not c_repo.list_by_project(project_id):
            created_constraints = c_repo.import_template(project_id, effective_type)
            imported_constraints_count = len(created_constraints)

    created_milestones_count = 0
    if request.seed_default_milestones:
        m_repo = ProjectMilestoneRepository()
        if not m_repo.list_by_project(project_id):
            for idx, item in enumerate(scaffold_result["default_milestones"]):
                m_repo.create(
                    project_id=project_id,
                    title=item["title"],
                    description=item.get("description"),
                    stage=item.get("stage"),
                    sort_order=idx + 1,
                )
                created_milestones_count += 1

    default_stage = scaffold_result.get("default_stage")
    final_stage = project.project_stage
    if not final_stage and default_stage:
        repo.update_project_stage(project_id, default_stage)
        final_stage = default_stage

    updated_project = _get_project_or_404(project_id)
    return ProjectScaffoldResponse(
        project=_with_stats(updated_project, repo.session_stats()),
        project_id=project_id,
        project_type=scaffold_result["project_type"],
        created_directories=scaffold_result["created_directories"],
        created_files=scaffold_result["created_files"],
        imported_constraints_count=imported_constraints_count,
        created_milestones_count=created_milestones_count,
        seeded_milestones_count=created_milestones_count,
        recommended_templates=scaffold_result["recommended_templates"],
        project_stage=final_stage,
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


@router.delete(
    "/{project_id}/constraints/{constraint_id}",
    response_model=MaterialMutationResponse,
)
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


@router.post(
    "/{project_id}/constraints/import-template",
    response_model=ConstraintsResponse,
    status_code=201,
)
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


@router.post(
    "/{project_id}/milestones",
    response_model=MilestoneModel,
    status_code=201,
)
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


@router.post(
    "/{project_id}/milestones/{milestone_id}/complete",
    response_model=MilestoneModel,
)
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


@router.delete(
    "/{project_id}/milestones/{milestone_id}",
    response_model=MaterialMutationResponse,
)
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


__all__ = ["router"]
