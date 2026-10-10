"""Pydantic request and response models for `/api/v1/projects` routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from backend.data.project_material_repo import MAX_MATERIAL_CONTENT_CHARS
from backend.office.models import _constrained_list


class ProjectRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1024)
    allowed_paths: Optional[_constrained_list(str, max_length=50)] = Field(default=None)
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
    status: Optional[str] = Field(
        default=None, pattern=r"^(pending|in_progress|completed|blocked)$"
    )
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


class GitCommitModel(BaseModel):
    """Git 提交记录。"""

    model_config = ConfigDict(extra="forbid")
    sha: str
    author: str
    date: str
    message: str


class GitStatusResponse(BaseModel):
    """Git 仓库状态响应。"""

    model_config = ConfigDict(extra="forbid")
    is_repo: bool
    current_branch: Optional[str] = None
    modified_files: List[str] = Field(default_factory=list)
    staged_files: List[str] = Field(default_factory=list)
    untracked_files: List[str] = Field(default_factory=list)
    recent_commits: List[GitCommitModel] = Field(default_factory=list)


class ProjectScaffoldRequest(BaseModel):
    """一键初始化项目组织结构请求（代码项目 / 一般档案 / 科研项目 / 个人空间）。"""

    model_config = ConfigDict(extra="forbid")
    project_type: Optional[str] = Field(
        default=None,
        pattern="^(coding|research|business|personal)$",
    )
    create_directories: bool = True
    create_sage_md: bool = True
    import_default_constraints: bool = True
    seed_default_milestones: bool = True


class ProjectScaffoldResponse(BaseModel):
    """一键初始化项目组织结构响应。"""

    model_config = ConfigDict(extra="forbid")
    project: ProjectModel
    project_id: str
    project_type: str
    created_directories: List[str] = Field(default_factory=list)
    created_files: List[str] = Field(default_factory=list)
    imported_constraints_count: int = 0
    created_milestones_count: int = 0
    seeded_milestones_count: int = 0
    recommended_templates: List[str] = Field(default_factory=list)
    project_stage: Optional[str] = None
