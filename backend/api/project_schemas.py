"""Pydantic request and response models for `/api/v1/projects` routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.compat.win7.pydantic_compat import ConfigDict
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
    # P3 (2026-11-05): 用户在创建对话框里选择的模板名。匹配顺序：
    # 全局模板库（load_global_templates）→ 内置模板（get_built_in_templates，
    # 按 project_type 匹配）。提供后会调用 scaffold_project 把目录/文件骨架
    # 写入项目根目录（幂等：已存在同名文件/目录跳过）。
    template_name: Optional[str] = Field(default=None, max_length=128)


class ProjectTemplateSummary(BaseModel):
    """``GET /projects/templates`` 单条。

    给前端模板选择器用，只暴露展示所需的元信息 + 目录/文件清单（不暴露
    file.content，避免响应过大；前端预览时按需走 preview 端点，v1 暂不实现）。
    """

    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    source: str  # "built_in" | "global"
    project_type: Optional[str] = None  # 内置模板对应 project_type；全局模板为 None
    directory_count: int = 0
    file_count: int = 0
    directories: List[str] = Field(default_factory=list)
    files: List[str] = Field(default_factory=list)


class ProjectTemplateListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    templates: List[ProjectTemplateSummary]


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
    project_sub_type: Optional[str] = None
    bootstrap_state: Optional[str] = None
    playbook_state: Optional[str] = None
    parent_id: Optional[str] = None
    discovery_source: Optional[str] = None
    status: str = "active"
    session_count: int = 0
    last_session_id: Optional[str] = None


class ProjectLocationResponse(BaseModel):
    """GET /projects/{id}/location 的响应：已校验的项目目录绝对路径。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    path: str


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Optional[str] = Field(default=None, max_length=4000)
    instructions: Optional[str] = Field(default=None, max_length=16000)
    project_type: Optional[str] = Field(
        default=None,
        pattern="^(coding|research|business|personal)$",
    )
    project_stage: Optional[str] = Field(default=None, max_length=64)
    project_sub_type: Optional[str] = Field(default=None, max_length=64)
    vcs_mode: Optional[str] = Field(
        default=None,
        pattern="^(git|builtin)$",
    )
    status: Optional[str] = Field(default=None, pattern="^(active|archived)$")


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
    enabled: bool = True


class ProjectMaterialsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materials: List[ProjectMaterialModel]


class ProjectMaterialUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class MaterialMutationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    removed: bool


class AddMaterialFromFileRequest(BaseModel):
    """POST /api/v1/projects/{id}/materials/from-file 请求体：将工作区文件纳入受控资料池。"""

    model_config = ConfigDict(extra="forbid")

    relative_path: str = Field(..., min_length=1, max_length=1024)


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
    # L2 子类型 key，None 表示仅识别到 L1
    sub_type: Optional[str] = None
    # 技术栈标记（package.json / pyproject.toml 等解析结果）
    tech_stack: List[str] = Field(default_factory=list)


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
    source: str = "user"
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
    parent_id: Optional[str] = None
    estimated_days: Optional[int] = None


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


class ProjectContextBudgetResponse(BaseModel):
    """项目五层受控上下文水位统计响应。"""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    l1_conventions_chars: int = 0
    l2_metadata_chars: int = 0
    l2_constraints_chars: int = 0
    l3_profile_chars: int = 0
    l4_materials_chars: int = 0
    total_chars: int = 0
    cap_chars: int = 16000
    per_file_cap_chars: int = 8000
    usage_ratio: float = 0.0
    active_materials_count: int = 0
    total_materials_count: int = 0
    enabled_constraints_count: int = 0
    synthesized_preview: str = ""


class WorkspaceArtifactItemModel(BaseModel):
    """工作区扫描出的文书/科研资产条目。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    relative_path: str
    ext: str
    category: str
    size_bytes: int
    modified_at: int


class WorkspaceDirectorySummaryModel(BaseModel):
    """工作区一级子目录文件统计。"""

    model_config = ConfigDict(extra="forbid")
    name: str
    file_count: int


class WorkspaceCheckpointItemModel(BaseModel):
    """内置版本控制检查点快照摘要。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    created_at: int
    file_count: int = 0


class CreateCheckpointRequest(BaseModel):
    """创建内置版本控制检查点请求体。"""

    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = Field(default=None, max_length=200)


class RestoreCheckpointResponse(BaseModel):
    """还原内置版本控制检查点响应。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    restored_files: List[str] = Field(default_factory=list)
    restored_at: int


class WorkspaceCheckpointDetailResponse(BaseModel):
    """内置版本控制检查点详情与快照预览响应。"""

    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    created_at: int
    file_count: int
    files: List[str] = Field(default_factory=list)
    snapshots: Dict[str, str] = Field(default_factory=dict)


class ProjectCharterResponse(BaseModel):
    """项目 L1 本地规范文件 SAGE.md 读取与保存响应。"""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    exists: bool
    content: str
    char_count: int
    recommended_template: str


class UpdateProjectCharterRequest(BaseModel):
    """更新项目 L1 本地规范文件 SAGE.md 请求体。"""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(default="", max_length=32000)


class ProjectWorkspaceOverviewResponse(BaseModel):
    """多形态项目工作区资产与环境概览响应。"""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    has_sage_md: bool = False
    has_hooks_json: bool = False
    checkpoint_count: int = 0
    latest_checkpoint_at: Optional[int] = None
    recent_checkpoints: List[WorkspaceCheckpointItemModel] = Field(default_factory=list)
    coding_indicators: List[str] = Field(default_factory=list)
    office_deliverables: List[WorkspaceArtifactItemModel] = Field(default_factory=list)
    research_artifacts: List[WorkspaceArtifactItemModel] = Field(default_factory=list)
    directory_summary: List[WorkspaceDirectorySummaryModel] = Field(default_factory=list)


class ProjectDiagnoseResponse(BaseModel):
    """项目运行环境满足度、测试入口与 Hooks 状态诊断响应。"""

    model_config = ConfigDict(extra="forbid")
    project_id: str
    level: str = "satisfied"
    detected_languages: List[str] = Field(default_factory=list)
    available_runtimes: List[str] = Field(default_factory=list)
    test_commands: List[str] = Field(default_factory=list)
    hooks_config_exists: bool = False
    hooks_count: int = 0
    hooks_trusted: bool = False
    recommendations: List[str] = Field(default_factory=list)


# ── AI 治理分析 schemas (2026-10-27) ─────────────────────────────────────────


class ProjectAnalyzeRequest(BaseModel):
    """POST /projects/analyze 或 /projects/profile 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1024)


class SourceSampleModel(BaseModel):
    """画像中的单个源码采样。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    language: str
    lines: int
    content: str


class GitStatsModel(BaseModel):
    """画像中的 Git 统计信息。"""

    model_config = ConfigDict(extra="forbid")

    is_repo: bool
    current_branch: Optional[str] = None
    commit_count: int = 0
    recent_commit_count: int = 0
    branch_count: int = 0
    last_commit_at: Optional[str] = None
    dirty_files: int = 0


class CodebaseProfileModel(BaseModel):
    """项目代码库画像。"""

    model_config = ConfigDict(extra="forbid")

    root: str
    level1_type: Optional[str] = None
    sub_type: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    build_commands: List[str] = Field(default_factory=list)
    test_frameworks: List[str] = Field(default_factory=list)
    lint_configs: List[str] = Field(default_factory=list)
    ci_workflows: List[str] = Field(default_factory=list)
    existing_rule_files: List[str] = Field(default_factory=list)
    directory_layout: List[str] = Field(default_factory=list)
    source_samples: List[SourceSampleModel] = Field(default_factory=list)
    git_stats: GitStatsModel
    vcs_mode: str = "unknown"


class ProjectProfileResponse(BaseModel):
    """POST /projects/profile 的响应。"""

    model_config = ConfigDict(extra="forbid")

    profile: CodebaseProfileModel


class SuggestedRuleModel(BaseModel):
    """分析报告中的单条规则建议。"""

    model_config = ConfigDict(extra="forbid")

    template_key: str
    label: str
    reason: str
    confidence: float
    category: str
    content: str
    trigger_pattern: str
    priority: int


class DocRefModel(BaseModel):
    """分析报告中引用的文档。"""

    model_config = ConfigDict(extra="forbid")

    title: str
    reason: str
    path: str


class AnalysisReportModel(BaseModel):
    """LLM 深度分析报告。"""

    model_config = ConfigDict(extra="forbid")

    level1_type: str
    sub_type: Optional[str] = None
    confidence: float = 0.0
    tech_stack: List[str] = Field(default_factory=list)
    architecture_summary: str = ""
    suggested_rules: List[SuggestedRuleModel] = Field(default_factory=list)
    governance_recommendations: List[str] = Field(default_factory=list)
    stage_recommendation: Optional[str] = None
    sage_md_draft: str = ""
    docs_refs: List[DocRefModel] = Field(default_factory=list)
    llm_available: bool = True
    raw_json: Optional[str] = None


class ProjectAnalyzeResponse(BaseModel):
    """POST /projects/analyze 的响应：画像 + 分析报告。"""

    model_config = ConfigDict(extra="forbid")

    profile: CodebaseProfileModel
    report: AnalysisReportModel


class RuleDraftModel(BaseModel):
    """规则草稿（待用户确认后落库）。"""

    model_config = ConfigDict(extra="forbid")

    category: str
    content: str
    trigger_pattern: str
    priority: int
    source: str
    template_key: str = ""
    reason: str = ""


class RuleGenerationRequest(BaseModel):
    """POST /projects/generate-rules 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    profile: Dict[str, Any]
    report: Dict[str, Any]
    project_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="若提供，将与项目已有约束去重",
    )


class RuleGenerationResultModel(BaseModel):
    """POST /projects/generate-rules 的响应。"""

    model_config = ConfigDict(extra="forbid")

    rules: List[RuleDraftModel] = Field(default_factory=list)
    milestones: List[Dict[str, str]] = Field(default_factory=list)
    llm_available: bool = True
    skipped_duplicates: int = 0


class SubTypesResponse(BaseModel):
    """GET /projects/sub-types 的响应。"""

    model_config = ConfigDict(extra="forbid")

    level1_types: List[str]
    sub_types: Dict[str, List[Dict[str, Any]]]


# ── AI bootstrap (2026-10-29) ───────────────────────────────────────────────


class BootstrapPreviewRequest(BaseModel):
    """POST /projects/{id}/bootstrap/preview 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    use_llm: bool = True


class BootstrapPreviewResponse(BaseModel):
    """POST /projects/{id}/bootstrap/preview 的响应。"""

    model_config = ConfigDict(extra="forbid")

    project: ProjectModel
    scan: Dict[str, Any]
    suggestions: Dict[str, Any]
    llm_available: bool
    llm_error: Optional[str] = None
    rule_source: Optional[str] = None


class BootstrapScanResponse(BaseModel):
    """POST /projects/{id}/bootstrap/scan 的响应（确定性扫描，不调用 LLM）。"""

    model_config = ConfigDict(extra="forbid")

    project: ProjectModel
    scan: Dict[str, Any]


class BootstrapSuggestResponse(BaseModel):
    """POST /projects/{id}/bootstrap/suggest 的响应（AI 建议阶段）。"""

    model_config = ConfigDict(extra="forbid")

    suggestions: Dict[str, Any]
    llm_available: bool
    llm_error: Optional[str] = None
    rule_source: Optional[str] = None


class BootstrapMetadataInput(BaseModel):
    """bootstrap apply 中可选的元数据更新。"""

    model_config = ConfigDict(extra="forbid")

    description: Optional[str] = Field(default=None, max_length=4000)
    instructions: Optional[str] = Field(default=None, max_length=16000)
    project_type: Optional[str] = Field(
        default=None, pattern="^(coding|research|business|personal)$"
    )
    project_sub_type: Optional[str] = Field(default=None, max_length=64)


class BootstrapRuleInput(BaseModel):
    """bootstrap apply 中的一条规则草稿。"""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=20000)
    trigger_pattern: Optional[str] = Field(default=None, max_length=256)
    priority: int = Field(default=5, ge=1, le=10)


class BootstrapMilestoneInput(BaseModel):
    """bootstrap apply 中的一个里程碑草稿。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    stage: Optional[str] = Field(default=None, max_length=64)
    estimated_days: Optional[float] = Field(default=None, ge=0, le=3650)


class BootstrapApplyRequest(BaseModel):
    """POST /projects/{id}/bootstrap/apply 的请求体。"""

    model_config = ConfigDict(extra="forbid")

    metadata: Optional[BootstrapMetadataInput] = None
    sage_md: bool = False
    sage_md_content: Optional[str] = Field(default=None, max_length=32000)
    overwrite_sage_md: bool = False
    rules: List[BootstrapRuleInput] = Field(default_factory=list)
    milestones: List[BootstrapMilestoneInput] = Field(default_factory=list)
    allowed_paths: Optional[_constrained_list(str, max_length=50)] = Field(default=None)
    git_init: bool = False
    initial_checkpoint: bool = False


class BootstrapErrorModel(BaseModel):
    """bootstrap apply 中单个失败项。"""

    model_config = ConfigDict(extra="forbid")

    item: str
    message: str


class BootstrapAppliedItem(BaseModel):
    """bootstrap apply 中单个已落地项（M3 验证明细）。"""

    model_config = ConfigDict(extra="forbid")

    item: str
    label: Optional[str] = None
    id: Optional[str] = None
    location: Optional[str] = None
    content_preview: Optional[str] = None


class BootstrapSkippedItem(BaseModel):
    """bootstrap apply 中单个跳过项（M3 验证明细）。"""

    model_config = ConfigDict(extra="forbid")

    item: str
    reason: str
    label: Optional[str] = None
    content_preview: Optional[str] = None


class BootstrapVerification(BaseModel):
    """bootstrap apply 之后对项目状态的复核结果。"""

    model_config = ConfigDict(extra="forbid")

    sage_md_exists: bool
    rules_count_after: int
    milestones_count_after: int


class BootstrapApplyResponse(BaseModel):
    """POST /projects/{id}/bootstrap/apply 的响应。"""

    model_config = ConfigDict(extra="forbid")

    project: ProjectModel
    applied: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    errors: List[BootstrapErrorModel] = Field(default_factory=list)
    applied_items: List[BootstrapAppliedItem] = Field(default_factory=list)
    skipped_items: List[BootstrapSkippedItem] = Field(default_factory=list)
    verification: Optional[BootstrapVerification] = None
    git: Optional[Dict[str, Any]] = None


class GitInitResponse(BaseModel):
    """POST /projects/{id}/git/init 的响应。"""

    model_config = ConfigDict(extra="forbid")

    initialized: bool
    already_repo: bool = False
    git_available: bool = True
    error: Optional[str] = None


class ProjectTreeResponse(BaseModel):
    """GET /projects/{id}/tree 的响应。

    ``root`` 是扫描得到的树（结构见 workspace_scanner.ScannedNode.to_dict：
    path / name / rel_path / role / discovery_source / children，另由路由补充
    已注册项目的 ``id``）。``role == "folder"`` 的节点仅作为容器存在，不对应
    项目行。
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str
    root: Dict[str, Any]
    symlinks: List[Dict[str, Any]] = Field(default_factory=list)
    truncated: List[str] = Field(default_factory=list)
    scanned_at: float
    created_project_ids: List[str] = Field(default_factory=list)
