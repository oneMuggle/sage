"""项目子类型定义（两级分类：L1 形态 + L2 技术栈子类型，2026-10-27）。

L1（`ProjectType`）保持 `coding / research / business / personal` 四值不变，
本模块在其下补充 L2 子类型，用于：
- 向用户解释「这类项目应该怎么治理」
- 让 LLM 分析有更精确的锚点
- 为子类型推荐默认约束模板与文档

子类型判定依赖「技术栈标记」而非目录结构猜测——标记命中即判定，
全部不命中时返回 None（只知 L1），不臆测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class SubTypeDefinition:
    """单个 L2 子类型定义。"""

    key: str
    label: str
    description: str
    #: 命中的技术栈标记（小写）。命中任一即判定为该子类型。
    markers: tuple = ()
    #: 判定该子类型要求的最小命中数。
    min_markers: int = 1
    #: 建议导入的约束模板 key。
    suggested_templates: tuple = ()
    #: 推荐里程碑阶段（L1 的 stage 命名空间）。
    stage: Optional[str] = None
    #: 补充文档建议（关键词，供分析报告展示）。
    doc_topics: tuple = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "suggested_templates": list(self.suggested_templates),
            "stage": self.stage,
            "doc_topics": list(self.doc_topics),
        }


# ── coding 子类型 ────────────────────────────────────────────────────────
CODING_SUBTYPES: List[SubTypeDefinition] = [
    SubTypeDefinition(
        key="python_backend",
        label="Python 后端服务",
        description="以 Python 构建的 API / 服务端应用，常见 FastAPI、Django、Flask 等框架。",
        markers=("fastapi", "django", "flask", "uvicorn", "sqlalchemy", "pydantic"),
        min_markers=1,
        suggested_templates=("coding", "python_default", "security_basic"),
        stage="planning",
        doc_topics=("python", "api-design"),
    ),
    SubTypeDefinition(
        key="typescript_frontend",
        label="TypeScript 前端应用",
        description="以 TypeScript 构建的 Web 前端，常见 React、Vue、Svelte 等框架。",
        markers=("react", "vue", "svelte", "vite", "next", "angular", "tailwind"),
        min_markers=1,
        suggested_templates=("coding", "typescript_react", "typescript_strict"),
        stage="planning",
        doc_topics=("frontend", "typescript"),
    ),
    SubTypeDefinition(
        key="desktop_app",
        label="桌面应用",
        description="Electron / Tauri 等跨平台桌面应用，通常包含前端渲染层与本地后端进程。",
        markers=("electron", "tauri", "electron-builder"),
        min_markers=1,
        suggested_templates=("coding", "typescript_strict", "security_basic"),
        stage="planning",
        doc_topics=("electron", "desktop"),
    ),
    SubTypeDefinition(
        key="data_science",
        label="数据科学与模型",
        description="以数据处理、建模与实验分析为主的项目，常见 pandas、NumPy、Jupyter、PyTorch。",
        markers=("pandas", "numpy", "jupyter", "notebook", "torch", "tensorflow", "scikit-learn"),
        min_markers=1,
        suggested_templates=("coding", "python_default", "citation_strict"),
        stage="planning",
        doc_topics=("data-science", "reproducibility"),
    ),
    SubTypeDefinition(
        key="rust_systems",
        label="Rust 系统工程",
        description="以 Rust 构建的高性能系统组件或服务，常见 Tokio、Axum、Serde。",
        markers=("cargo", "tokio", "axum", "serde", "actix"),
        min_markers=1,
        suggested_templates=("coding", "security_basic"),
        stage="planning",
        doc_topics=("rust", "systems"),
    ),
    SubTypeDefinition(
        key="go_services",
        label="Go 微服务",
        description="以 Go 构建的高并发服务或命令行工具，常见 Gin、gRPC。",
        markers=("gin-gonic", "grpc", "go-kit", "gorilla", "cobra"),
        min_markers=1,
        suggested_templates=("coding", "security_basic"),
        stage="planning",
        doc_topics=("go", "microservice"),
    ),
    SubTypeDefinition(
        key="java_spring",
        label="Java / Spring 服务",
        description="以 Java 与 Spring 生态构建的企业级后端服务。",
        markers=("spring-boot", "springframework", "hibernate", "maven"),
        min_markers=1,
        suggested_templates=("coding", "security_basic", "architecture_guard"),
        stage="planning",
        doc_topics=("java", "spring"),
    ),
    SubTypeDefinition(
        key="mobile_app",
        label="移动应用",
        description="React Native、Flutter 等跨平台移动端应用。",
        markers=("react-native", "flutter", "expo", "android", "ionic"),
        min_markers=1,
        suggested_templates=("coding", "typescript_strict", "security_basic"),
        stage="planning",
        doc_topics=("mobile",),
    ),
]

# ── research 子类型 ──────────────────────────────────────────────────────
RESEARCH_SUBTYPES: List[SubTypeDefinition] = [
    SubTypeDefinition(
        key="academic_paper",
        label="学术论文",
        description="以投稿、撰写与修回为主线的科研论文项目。",
        markers=("latex", "bibtex", "elsarticle", "ieeetran", "overleaf"),
        min_markers=1,
        suggested_templates=("research", "academic_writing", "citation_strict"),
        stage="writing",
        doc_topics=("academic-writing", "citation"),
    ),
    SubTypeDefinition(
        key="grant_proposal",
        label="基金 / 课题申报",
        description="以立项依据、研究方案与可行性分析为主线的申请书项目。",
        markers=("nsfc", "基金", "申请书", "proposal", "申报书"),
        min_markers=1,
        suggested_templates=("research", "grant_proposal", "nsfc_grant_style"),
        stage="proposal",
        doc_topics=("grant", "proposal"),
    ),
    SubTypeDefinition(
        key="literature_review",
        label="文献综述",
        description="以文献系统调研、方法对比与研究空白梳理为主线。",
        markers=("zotero", "mendeley", "综述", "review"),
        min_markers=1,
        suggested_templates=("research", "academic_writing", "citation_zero_hallucination"),
        stage="proposal",
        doc_topics=("literature-review",),
    ),
    SubTypeDefinition(
        key="lab_experiment",
        label="实验与数据分析",
        description="以实验执行、数据采集与结果分析为主线的实验项目。",
        markers=("notebook", "ipynb", "jupyter", "实验记录", "lab"),
        min_markers=1,
        suggested_templates=("research", "academic_writing", "citation_strict"),
        stage="analysis",
        doc_topics=("experiment", "reproducibility"),
    ),
]

# ── business 子类型 ──────────────────────────────────────────────────────
BUSINESS_SUBTYPES: List[SubTypeDefinition] = [
    SubTypeDefinition(
        key="contract_mgmt",
        label="合同与法务审查",
        description="以商务合同起草、条款核验与合规会签为主线。",
        markers=("合同", "协议", "contract", "甲方", "乙方"),
        min_markers=1,
        suggested_templates=("business", "contract_review", "document_format"),
        stage="execution",
        doc_topics=("contract", "compliance"),
    ),
    SubTypeDefinition(
        key="report_writing",
        label="报告与公文写作",
        description="以公文、请示报告与制度文件编制为主线。",
        markers=("公文", "请示", "报告", "gb/t 9704", "红头文件"),
        min_markers=1,
        suggested_templates=("business", "document_format", "archive_dossier_cn"),
        stage="execution",
        doc_topics=("document-format",),
    ),
    SubTypeDefinition(
        key="archive_dossier",
        label="案卷归档",
        description="以立卷归集、原始佐证保护与定稿封存为主线。",
        markers=("立卷", "案卷", "归档", "密级", "卷宗"),
        min_markers=1,
        suggested_templates=("business", "archive_dossier_cn", "document_format"),
        stage="initiation",
        doc_topics=("archive",),
    ),
    SubTypeDefinition(
        key="presentation",
        label="演示与汇报材料",
        description="以演示文稿、汇报与路演材料编制为主线。",
        markers=("演示", "汇报", "路演", "ppt", "slide"),
        min_markers=1,
        suggested_templates=("business", "document_format"),
        stage="execution",
        doc_topics=("presentation",),
    ),
]

# ── personal 子类型 ──────────────────────────────────────────────────────
PERSONAL_SUBTYPES: List[SubTypeDefinition] = [
    SubTypeDefinition(
        key="knowledge_base",
        label="知识卡片库",
        description="以读书卡片、概念沉淀与双链索引为主线的个人知识库。",
        markers=("卡片", "双链", "obsidian", "notes", "inbox"),
        min_markers=1,
        suggested_templates=("personal", "concise_note_taking"),
        stage="active",
        doc_topics=("note-taking",),
    ),
    SubTypeDefinition(
        key="journal",
        label="日志与复盘",
        description="以日志记录、周期复盘与经验沉淀为主线。",
        markers=("日志", "复盘", "journal", "diary", "retro"),
        min_markers=1,
        suggested_templates=("personal", "concise_note_taking"),
        stage="active",
        doc_topics=("journal",),
    ),
    SubTypeDefinition(
        key="todo_planning",
        label="目标与任务规划",
        description="以目标拆解、任务追踪与周期计划为主线。",
        markers=("okr", "todo", "任务", "计划", "roadmap"),
        min_markers=1,
        suggested_templates=("personal", "concise_note_taking"),
        stage="active",
        doc_topics=("planning",),
    ),
    SubTypeDefinition(
        key="learning_notes",
        label="学习笔记",
        description="以课程学习笔记与知识整理为主线。",
        markers=("课程", "学习", "course", "lecture", "教程"),
        min_markers=1,
        suggested_templates=("personal", "concise_note_taking"),
        stage="active",
        doc_topics=("learning",),
    ),
]


SUB_TYPES_BY_LEVEL1: Dict[str, List[SubTypeDefinition]] = {
    "coding": CODING_SUBTYPES,
    "research": RESEARCH_SUBTYPES,
    "business": BUSINESS_SUBTYPES,
    "personal": PERSONAL_SUBTYPES,
}

#: 所有 L1 类型（保持与 `ProjectType` 一致）。
LEVEL1_TYPES: List[str] = list(SUB_TYPES_BY_LEVEL1.keys())

#: 扁平索引：sub_type key -> 定义
_SUB_TYPE_INDEX: Dict[str, SubTypeDefinition] = {
    st.key: st for st_list in SUB_TYPES_BY_LEVEL1.values() for st in st_list
}

#: 技术栈标记 -> 可能的子类型 key（用于按标记反查候选）
_MARKER_TO_SUBTYPES: Dict[str, List[str]] = {}
for _st in _SUB_TYPE_INDEX.values():
    for _marker in _st.markers:
        _MARKER_TO_SUBTYPES.setdefault(_marker, []).append(_st.key)


def get_sub_type(sub_type: Optional[str]) -> Optional[SubTypeDefinition]:
    """按 key 获取子类型定义。"""
    if not sub_type:
        return None
    return _SUB_TYPE_INDEX.get(sub_type)


def list_sub_types(level1_type: Optional[str] = None) -> List[SubTypeDefinition]:
    """列出子类型定义。`level1_type` 为 None 时返回全部。"""
    if not level1_type:
        return list(_SUB_TYPE_INDEX.values())
    return list(SUB_TYPES_BY_LEVEL1.get(level1_type, []))


def candidate_sub_types(markers: List[str]) -> List[str]:
    """根据技术栈标记返回候选子类型 key（按命中数降序）。"""
    lowered = [m.lower() for m in markers if m]
    hit_counts: Dict[str, int] = {}
    for marker in lowered:
        for key in _MARKER_TO_SUBTYPES.get(marker, []):
            hit_counts[key] = hit_counts.get(key, 0) + 1
    if not hit_counts:
        return []
    return [k for k, _ in sorted(hit_counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def match_sub_type(
    markers: List[str],
    level1_type: Optional[str] = None,
) -> Optional[SubTypeDefinition]:
    """按技术栈标记匹配子类型。

    只在候选子类型属于 `level1_type` 时才返回（若给定），避免跨形态误判。
    全部不命中返回 None——宁可只知 L1，也不臆测。
    """
    allowed = (
        {st.key for st in SUB_TYPES_BY_LEVEL1.get(level1_type, [])}
        if level1_type
        else None
    )
    for key in candidate_sub_types(markers):
        definition = _SUB_TYPE_INDEX.get(key)
        if definition is None:
            continue
        if allowed is not None and key not in allowed:
            continue
        if _hit_count(definition, markers) >= definition.min_markers:
            return definition
    return None


def _hit_count(definition: SubTypeDefinition, markers: List[str]) -> int:
    """统计子类型标记命中数。"""
    lowered = {m.lower() for m in markers if m}
    return sum(1 for marker in definition.markers if marker.lower() in lowered)


def sub_types_payload(level1_type: Optional[str] = None) -> dict:
    """构造 API 响应载荷。"""
    if level1_type:
        groups = {
            level1_type: [st.to_dict() for st in SUB_TYPES_BY_LEVEL1.get(level1_type, [])]
        }
    else:
        groups = {
            level1: [st.to_dict() for st in st_list]
            for level1, st_list in SUB_TYPES_BY_LEVEL1.items()
        }
    return {"level1_types": LEVEL1_TYPES, "sub_types": groups}


__all__ = [
    "BUSINESS_SUBTYPES",
    "CODING_SUBTYPES",
    "LEVEL1_TYPES",
    "PERSONAL_SUBTYPES",
    "RESEARCH_SUBTYPES",
    "SUB_TYPES_BY_LEVEL1",
    "SubTypeDefinition",
    "candidate_sub_types",
    "get_sub_type",
    "list_sub_types",
    "match_sub_type",
    "sub_types_payload",
]
