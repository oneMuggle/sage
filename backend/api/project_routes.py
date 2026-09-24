"""Typed HTTP routes for the projects registry (项目模块 P1, 2026-09-13).

"项目" = 用户在侧边栏显式登记的工作目录（对标 Cursor Recent Workspaces /
Claude Code 项目 → 会话归属）。路由面刻意保持最小：

- ``GET  /projects``                     清单（按最近打开排序，附会话聚合）
- ``POST /projects``                     登记目录（validate_workspace 校验，幂等）
- ``DELETE /projects/{project_id}``      从清单移除（不动磁盘与会话）
- ``POST /projects/{project_id}/open``   打开项目：复用最近会话或新建并绑定
- ``GET  /projects/{project_id}/sessions`` 项目下未归档会话（新→旧）

会话与目录的归属复用 ``session_workspace_bindings`` 活跃绑定（见
``backend/data/project_repo.py`` 模块注释），本文件不做第二份归属数据。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.data.database import get_database, make_with_db_lock
from backend.data.project_material_repo import (
    MAX_MATERIAL_CONTENT_CHARS,
    ProjectMaterial,
    ProjectMaterialContentTooLargeError,
    ProjectMaterialRepository,
)
from backend.data.project_repo import (
    Project,
    ProjectNotFoundError,
    ProjectPathMissingError,
    ProjectRepository,
    open_project,
)
from backend.data.project_constraint_repo import (
    CONSTRAINT_TEMPLATES,
    ProjectConstraint,
    ProjectConstraintRepository,
)
from backend.data.project_milestone_repo import (
    MILESTONE_STATUS,
    PROJECT_STAGE_ENUM,
    ProjectMilestone,
    ProjectMilestoneRepository,
)
from backend.data.session_repo import MessageRepository
from backend.office.errors import OfficePathError
from backend.office.models import _constrained_list
from backend.office.session_workspace import get_workspace_binding
from backend.services.project_type_detector import (
    DetectionResult,
    detect_project_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


# review HIGH #3 fix: 用本地装饰器模式（参见 backend/api/legacy_routes.py
# 同样的做法, 23 处引用）。所有 SQL 读写统一串行化到进程级 _SQLITE_LOCK。
def with_db_lock(func):
    return make_with_db_lock(globals())(func)


class ProjectRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    allowed_paths: Optional[_constrained_list(str, max_length=50)] = Field(default=None)
    # Project type classification (2026-09-24)
    project_type: Optional[str] = Field(
        default=None,
        pattern="^(coding|research|business|personal)$",
        description="项目类型。null = 使用自动检测结果",
    )


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str
    name: str
    created_at: int
    last_opened_at: int
    allowed_paths: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    instructions: Optional[str] = None
    # Project type classification (2026-09-24)
    project_type: Optional[str] = None
    project_stage: Optional[str] = None
    vcs_mode: str = "builtin"
    detected_type: Optional[str] = None
    session_count: int = 0
    last_session_id: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = Field(default=None, max_length=4000)
    instructions: Optional[str] = Field(default=None, max_length=16000)
    # Project type classification (2026-09-24)
    project_type: Optional[str] = Field(
        default=None,
        pattern="^(coding|research|business|personal)$",
    )
    project_stage: Optional[str] = Field(default=None, max_length=64)


class ProjectMaterialAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=MAX_MATERIAL_CONTENT_CHARS)
    source_message_id: Optional[str] = Field(default=None, max_length=256)


class ProjectMaterialModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    source_message_id: Optional[str]
    content_hash: str
    content: str
    status: str
    wiki_page_path: Optional[str]
    error_message: Optional[str]
    created_at: int


class ProjectMaterialsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materials: List[ProjectMaterialModel]


class MaterialMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    removed: bool


class SaveAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=256)


class ProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projects: List[ProjectModel]


class ProjectMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    removed: bool


class ProjectOpenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: ProjectModel
    session: Dict[str, Any]
    created: bool


class ProjectSessionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: List[Dict[str, Any]]


class ProjectAllowedPathsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_paths: _constrained_list(str, max_length=50) = Field(...)


class ProjectAllowedPathsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    allowed_paths: List[str]


# Project type detection (2026-09-24)
class ProjectTypeDetectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)


class DetectionSignalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    weight: float


class ProjectTypeDetectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_type: Optional[str]
    confidence: float
    signals: List[DetectionSignalModel]


# Project constraints (2026-09-24)
class ConstraintCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=4000)
    trigger_pattern: Optional[str] = Field(default=None, max_length=256)
    priority: int = Field(default=5, ge=1, le=10)


class ConstraintUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Optional[str] = Field(default=None, min_length=1, max_length=64)
    content: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    trigger_pattern: Optional[str] = Field(default=None, max_length=256)
    priority: Optional[int] = Field(default=None, ge=1, le=10)
    enabled: Optional[bool] = None


class ConstraintModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    category: str
    content: str
    trigger_pattern: Optional[str]
    priority: int
    enabled: bool
    created_at: int
    updated_at: int


class ConstraintsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    constraints: List[ConstraintModel]


class ConstraintTemplateImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: str = Field(min_length=1, max_length=64)


class ConstraintTemplatesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    templates: Dict[str, List[Dict[str, Any]]]


# Project milestones (2026-09-24)
class MilestoneCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)
    stage: Optional[str] = Field(default=None, max_length=64)
    due_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sort_order: int = Field(default=0, ge=0)


class MilestoneUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)
    stage: Optional[str] = Field(default=None, max_length=64)
    due_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: Optional[str] = Field(default=None, pattern=r"^(pending|in_progress|completed|blocked)$")
    sort_order: Optional[int] = Field(default=None, ge=0)


class MilestoneModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    project_id: str
    title: str
    description: Optional[str]
    stage: Optional[str]
    due_date: Optional[str]
    completed_at: Optional[int]
    status: str
    sort_order: int
    created_at: int


class MilestonesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    milestones: List[MilestoneModel]


class ProjectTypeConfigResponse(BaseModel):
    """项目类型配置（阶段枚举、约束模板列表）。"""
    model_config = ConfigDict(extra="forbid")
    stage_enum: Dict[str, Optional[List[str]]]
    milestone_status: List[str]
    constraint_templates: List[str]


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
    return ProjectListResponse(
        projects=[_with_stats(p, stats) for p in repo.list()]
    )


@router.post("", response_model=ProjectModel)
@with_db_lock
def register_project(request: ProjectRegisterRequest) -> ProjectModel:
    try:
        # 自动类型检测（如果用户未显式指定）
        detected_type = None
        project_type = request.project_type
        if project_type is None:
            from pathlib import Path
            result = detect_project_type(Path(request.path))
            detected_type = result.project_type
            project_type = detected_type  # 使用检测结果作为默认值

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
def update_project(
    project_id: str, request: ProjectUpdateRequest
) -> ProjectModel:
    """更新项目概览字段。未出现在请求中的字段保持不变。"""
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")

    fields_set = getattr(request, "model_fields_set", request.__fields_set__)
    if "description" in fields_set:
        repo.update_description(project_id, request.description)
    if "instructions" in fields_set:
        repo.update_instructions(project_id, request.instructions)
    # Project type classification (2026-09-24)
    if "project_type" in fields_set:
        repo.update_project_type(project_id, request.project_type)
    if "project_stage" in fields_set:
        repo.update_project_stage(project_id, request.project_stage)

    updated = repo.get(project_id)
    assert updated is not None
    return _with_stats(updated, repo.session_stats())


@router.put("/{project_id}/allowed-paths", response_model=ProjectAllowedPathsResponse)
@with_db_lock
def update_project_allowed_paths(
    project_id: str, request: ProjectAllowedPathsRequest
) -> ProjectAllowedPathsResponse:
    """更新项目 allowed_paths（2026-09-17 扩展）。

    用户可在前端项目详情面板管理额外允许访问的路径规则。
    """
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
    return ProjectMaterialsResponse(
        materials=[_material_model(material) for material in materials]
    )


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


@router.delete(
    "/{project_id}/materials/{material_id}",
    response_model=MaterialMutationResponse,
)
@with_db_lock
def remove_project_material(
    project_id: str, material_id: str
) -> MaterialMutationResponse:
    _get_project_or_404(project_id)
    materials = ProjectMaterialRepository()
    material = materials.get(material_id)
    if material is None or material.project_id != project_id:
        raise _error(404, "material_not_found", "资料不存在")
    if not materials.remove(material_id):
        raise _error(404, "material_not_found", "资料不存在")
    return MaterialMutationResponse(removed=True)


@router.post(
    "/{project_id}/materials/save-answer",
    response_model=ProjectMaterialModel,
    status_code=201,
)
@with_db_lock
def save_answer_as_project_material(
    project_id: str, request: SaveAnswerRequest
) -> ProjectMaterialModel:
    """把当前项目绑定会话中的可见回答保存为项目资料。

    security MEDIUM fix: 仅允许 role == "assistant" 的消息——用户消息
    (role=user) 内容可能携带 prompt injection 指令,不应直接进入项目
    资料上下文(后续会被注入 LLM prompt)。
    """
    project = _get_project_or_404(project_id)
    message = MessageRepository().get(request.message_id)
    if message is None:
        raise _error(404, "message_not_found", "消息不存在")
    # security: 拒绝非 assistant 消息——避免 user-role 内容注入项目资料
    if message.role != "assistant":
        raise _error(
            400,
            "message_role_not_savable",
            "仅可保存助手回答,用户消息不允许作为项目资料",
        )

    binding = get_workspace_binding(
        get_database().get_connection(), message.session_id
    )
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

    目录在磁盘上已消失 → 410 ``project_path_missing``（前端据此提示
    移除该项目或重新选择目录），不静默重建绑定。
    """
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


@router.get("/{project_id}/sessions", response_model=ProjectSessionsResponse)
@with_db_lock
def list_project_sessions(project_id: str) -> ProjectSessionsResponse:
    repo = ProjectRepository()
    project = repo.get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    sessions = repo.sessions_for_project(project.path)
    return ProjectSessionsResponse(sessions=[s.to_dict() for s in sessions])


# Project type detection API (2026-09-24)
@router.post("/detect-type", response_model=ProjectTypeDetectResponse)
def detect_project_type_route(request: ProjectTypeDetectRequest) -> ProjectTypeDetectResponse:
    """预览项目类型检测结果（不注册项目）。

    扫描目录内容推断项目类型，返回检测结果和置信度，
    供前端在项目创建向导中显示建议类型。
    """
    from pathlib import Path

    try:
        path = Path(request.path).expanduser().resolve()
        if not path.is_dir():
            raise _error(400, "path_not_directory", "路径不存在或不是目录")
        result: DetectionResult = detect_project_type(path)
        return ProjectTypeDetectResponse(
            project_type=result.project_type,
            confidence=result.confidence,
            signals=[
                DetectionSignalModel(type=s.type, weight=s.weight)
                for s in result.signals
            ],
        )
    except OSError as exc:
        raise _error(400, "path_error", f"路径错误: {exc}") from exc


# ── Project constraints routes (2026-09-24) ──────────────────────────────────


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
def create_constraint(
    project_id: str, request: ConstraintCreateRequest
) -> ConstraintModel:
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

    fields_set = getattr(request, "model_fields_set", request.__fields_set__)
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


@router.get("/templates/constraints", response_model=ConstraintTemplatesResponse)
def list_constraint_templates() -> ConstraintTemplatesResponse:
    """列出可用的约束模板。"""
    return ConstraintTemplatesResponse(
        templates={name: items for name, items in CONSTRAINT_TEMPLATES.items()}
    )


# ── Project milestones routes (2026-09-24) ───────────────────────────────────


@router.get("/{project_id}/milestones", response_model=MilestonesResponse)
@with_db_lock
def list_milestones(
    project_id: str, status: Optional[str] = None
) -> MilestonesResponse:
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
def create_milestone(
    project_id: str, request: MilestoneCreateRequest
) -> MilestoneModel:
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

    fields_set = getattr(request, "model_fields_set", request.__fields_set__)
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
    return _milestone_model(repo.get(milestone_id))


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
    return _milestone_model(repo.get(milestone_id))


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


# ── Project type config (2026-09-24) ─────────────────────────────────────────


@router.get("/config/types", response_model=ProjectTypeConfigResponse)
def get_project_type_config() -> ProjectTypeConfigResponse:
    """获取项目类型配置（阶段枚举、约束模板列表）。"""
    return ProjectTypeConfigResponse(
        stage_enum=PROJECT_STAGE_ENUM,
        milestone_status=MILESTONE_STATUS,
        constraint_templates=list(CONSTRAINT_TEMPLATES.keys()),
    )


__all__ = ["router"]
