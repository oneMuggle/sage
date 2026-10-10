"""多项目形态组织脚手架服务（代码项目 / 一般档案 / 科研项目 / 个人空间，2026-10-10）。

基于项目的 `project_type` 提供标准化目录结构、初始 `SAGE.md` 模板、推荐约束模板与初始阶段里程碑：
- `coding`（代码工程项目）：Repo-Native & Rule-Triggered
- `business`（一般档案与办公文书项目）：Dossier-Centric & Template-Governed
- `research`（科学研究与课题项目）：Source-Grounded & Hypothesis-Driven
- `personal`（个人知识空间）：Personal Knowledge Vault
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ArchetypeBlueprint:
    """单一项目形态的组织蓝图定义。"""

    project_type: str
    label_zh: str
    label_en: str
    default_stage: Optional[str]
    default_vcs_mode: str
    directories: List[str] = field(default_factory=list)
    recommended_templates: List[str] = field(default_factory=list)
    default_milestones: List[Dict[str, str]] = field(default_factory=list)
    sage_md_template: str = ""


ARCHETYPE_BLUEPRINTS: Dict[str, ArchetypeBlueprint] = {
    "coding": ArchetypeBlueprint(
        project_type="coding",
        label_zh="代码工程项目",
        label_en="Code & Engineering Project",
        default_stage="planning",
        default_vcs_mode="git",
        directories=["src", "tests", "docs"],
        recommended_templates=["coding", "python_default", "typescript_react", "security_basic"],
        default_milestones=[
            {"title": "架构设计与模块边界定义", "stage": "planning", "description": "明确分层架构、接口契约与构建检查门禁"},
            {"title": "核心功能开发与模块联调", "stage": "development", "description": "完成核心业务逻辑实现并通过静态类型检查"},
            {"title": "单元测试覆盖与回归验证", "stage": "testing", "description": "补充关键路径单元测试并通过 CI 门禁"},
        ],
        sage_md_template=(
            "# {project_name} — 项目工程规范 (SAGE.md)\n\n"
            "## 1. 项目定位与架构边界\n"
            "- **项目类型**：代码工程项目 (`coding`)\n"
            "- **核心目标**：在此简述仓库核心职责、技术栈与分层约束。\n\n"
            "## 2. 常用研发与验证命令\n"
            "- 构建与类型检查：`npm run typecheck` / `pytest`\n"
            "- 代码规范检查：`npm run lint`\n\n"
            "## 3. AI 协同开发红线\n"
            "- 修改核心逻辑前先阅读相关模块与现有测试，保持最小侵入式变更。\n"
            "- 严禁硬编码敏感凭据，新增公共接口须同步补充单元测试。\n"
        ),
    ),
    "business": ArchetypeBlueprint(
        project_type="business",
        label_zh="一般档案与文书项目",
        label_en="General Archive & Dossier Project",
        default_stage="initiation",
        default_vcs_mode="builtin",
        directories=[
            "00_立项与背景材料",
            "01_原始依据与佐证",
            "02_编制中工作稿",
            "03_定稿与签发归档",
        ],
        recommended_templates=["business", "document_format", "archive_dossier_cn", "contract_review"],
        default_milestones=[
            {"title": "立卷建档与原始依据归集", "stage": "initiation", "description": "完成背景文件、政策依据及合同范本整理归档"},
            {"title": "工作稿编制与版式规范排版", "stage": "execution", "description": "在 02_编制中工作稿 目录完成主体文书与报表起草"},
            {"title": "合规审校与签发封卷归档", "stage": "closure", "description": "完成保密等级、金额大小写与术语核对，移入 03_定稿与签发归档"},
        ],
        sage_md_template=(
            "# {project_name} — 数字案卷总纲 (SAGE.md)\n\n"
            "## 1. 案卷基础元数据\n"
            "- **项目类型**：一般档案与办公文书 (`business`)\n"
            "- **案卷编号 / 密级**：内部受控 / 待填写编号\n"
            "- **文种与版式规范**：遵循标准公文/商务文书版式，金额与日期须大小写双校验。\n\n"
            "## 2. 案卷目录受控约定\n"
            "- `00_立项与背景材料/`：存放任务通知、会议纪要与立项说明。\n"
            "- `01_原始依据与佐证/`：**只读原始凭据区**，AI 仅可引用核对，严禁修改或覆盖。\n"
            "- `02_编制中工作稿/`：存放正在协同起草与修订的 Word/Excel/PPT 工作稿。\n"
            "- `03_定稿与签发归档/`：存放终审定稿文件与归档核验清单。\n"
        ),
    ),
    "research": ArchetypeBlueprint(
        project_type="research",
        label_zh="科学研究与课题项目",
        label_en="Scientific Research Project",
        default_stage="proposal",
        default_vcs_mode="builtin",
        directories=[
            "01_literature",
            "02_experiments_and_data",
            "03_manuscript",
            "04_submission_and_rebuttal",
        ],
        recommended_templates=["research", "academic_writing", "citation_strict", "grant_proposal"],
        default_milestones=[
            {"title": "开题立项与核心文献精读综述", "stage": "proposal", "description": "提炼研究问题 (RQ)、科学假设并建立文献对比矩阵"},
            {"title": "实验设计与基线/消融数据分析", "stage": "analysis", "description": "记录完整实验超参、随机种子与显著性检验结果"},
            {"title": "论文手稿撰写与引文零幻觉核验", "stage": "writing", "description": "完成手稿图表排版并逐条核查 .bib 引用真实性"},
        ],
        sage_md_template=(
            "# {project_name} — 科研课题总纲 (SAGE.md)\n\n"
            "## 1. 核心研究问题 (Research Questions) 与假设\n"
            "- **研究问题 (RQ1)**：待提炼核心科学问题\n"
            "- **核心假设 (Hypothesis)**：待阐述方法创新点与理论预期\n"
            "- **目标期刊/会议与引文格式**：APA / IEEE / GB/T 7714\n\n"
            "## 2. 数学符号与术语规范表 (Notation Table)\n"
            "- 在此维护全课题统一的数学符号、缩写词与指标定义。\n\n"
            "## 3. 学术诚信与引用强护栏\n"
            "- **零幻觉引用铁律**：严禁编造任何参考文献、作者或 DOI；所有引用必须关联 `01_literature/` 或项目已索引资料。\n"
            "- **可复现实验准则**：实验分析必须记录日期、参数配置、定量均值±标准差及误差分析。\n"
        ),
    ),
    "personal": ArchetypeBlueprint(
        project_type="personal",
        label_zh="个人知识与日常空间",
        label_en="Personal Knowledge Vault",
        default_stage=None,
        default_vcs_mode="builtin",
        directories=["00_inbox", "01_notes", "02_references", "03_archive"],
        recommended_templates=["personal"],
        default_milestones=[
            {"title": "整理收件箱与建立核心知识索引", "stage": "active", "description": "归档散落笔记并提炼长期个人记忆卡片"},
        ],
        sage_md_template=(
            "# {project_name} — 个人知识空间约定 (SAGE.md)\n\n"
            "- **定位**：个人笔记、专题阅读与日常事务归档空间。\n"
            "- **原则**：结论先行、结构化要点沉淀，敏感个人信息自动脱敏。\n"
        ),
    ),
}


def get_archetype_blueprint(project_type: Optional[str]) -> ArchetypeBlueprint:
    """按项目类型返回对应蓝图（未知或空类型回退为 business 一般档案蓝图）。"""
    key = (project_type or "business").strip().lower()
    return ARCHETYPE_BLUEPRINTS.get(key, ARCHETYPE_BLUEPRINTS["business"])


def scaffold_project_archetype(
    workspace_path: Path,
    project_type: Optional[str],
    project_name: Optional[str] = None,
    *,
    create_directories: bool = True,
    create_sage_md: bool = True,
) -> Dict[str, Any]:
    """在指定项目目录下按项目形态初始化标准子目录与 SAGE.md（幂等、绝不覆盖已有文件）。"""
    blueprint = get_archetype_blueprint(project_type)
    name = (project_name or workspace_path.name or "Project").strip()

    created_dirs: List[str] = []
    if create_directories:
        for rel_dir in blueprint.directories:
            target = workspace_path / rel_dir
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                created_dirs.append(rel_dir)

    created_files: List[str] = []
    sage_md_path = workspace_path / "SAGE.md"
    if create_sage_md and not sage_md_path.exists() and blueprint.sage_md_template:
        content = blueprint.sage_md_template.format(project_name=name)
        sage_md_path.write_text(content, encoding="utf-8")
        created_files.append("SAGE.md")

    return {
        "project_type": blueprint.project_type,
        "created_directories": created_dirs,
        "created_files": created_files,
        "recommended_templates": list(blueprint.recommended_templates),
        "default_stage": blueprint.default_stage,
        "default_milestones": list(blueprint.default_milestones),
    }


__all__ = [
    "ARCHETYPE_BLUEPRINTS",
    "ArchetypeBlueprint",
    "get_archetype_blueprint",
    "scaffold_project_archetype",
]
