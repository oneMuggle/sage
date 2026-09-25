"""Wiki 模板按项目类型初始化 (2026-09-25)

项目类型分类系统 - Phase 9.5.1
根据项目类型生成不同的 Wiki 目录结构和初始页面。

各类型默认结构：
- coding: API 文档、架构概览、Changelog、ADR、运维手册
- research: 文献综述、实验记录、数据索引、方法论、投稿追踪
- business: 项目章程、会议纪要、交付物、里程碑、风险登记
- personal: 收件箱、笔记、知识库
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class WikiPageTemplate:
    """Wiki 页面模板"""

    relative_path: str
    title: str
    content: str


@dataclass
class WikiTemplate:
    """项目类型的 Wiki 模板定义"""

    project_type: str
    directories: List[str] = field(default_factory=list)
    pages: List[WikiPageTemplate] = field(default_factory=list)


# ---------- 通用基础结构（所有类型共享） ----------

_COMMON_DIRECTORIES = [
    "raw/sources",
    "raw/assets",
    ".llm-wiki",
]

_COMMON_PAGES: List[WikiPageTemplate] = []


# ---------- Coding 项目 ----------

_CODING_TEMPLATE = WikiTemplate(
    project_type="coding",
    directories=[
        "wiki/api-docs",
        "wiki/architecture",
        "wiki/changelog",
        "wiki/adr",
        "wiki/runbook",
    ],
    pages=[
        WikiPageTemplate(
            relative_path="wiki/schema.md",
            title="Schema",
            content=(
                "# Schema\n\n"
                "本项目的 Wiki 结构定义。\n\n"
                "## 目录结构\n\n"
                "- `raw/sources/` - 原始文档（不可变）\n"
                "- `raw/assets/` - 附件资源\n"
                "- `wiki/api-docs/` - API 文档（自动从代码生成）\n"
                "- `wiki/architecture/` - 架构概览（import 关系图）\n"
                "- `wiki/changelog/` - Changelog（git log 聚合）\n"
                "- `wiki/adr/` - 架构决策记录\n"
                "- `wiki/runbook/` - 运维手册\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/overview.md",
            title="Overview",
            content=(
                "# {project_name}\n\n"
                "## 概述\n\n"
                "编码项目的 Wiki 知识库。\n\n"
                "## 页面\n\n"
                "- [API 文档](api-docs/) - 自动生成的 API 文档\n"
                "- [架构概览](architecture/) - 系统架构和设计\n"
                "- [Changelog](changelog/) - 版本变更记录\n"
                "- [ADR](adr/) - 架构决策记录\n"
                "- [运维手册](runbook/) - 部署和运维指南\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/index.md",
            title="Index",
            content=(
                "# Wiki 索引\n\n"
                "## API 文档\n\n"
                "_运行自动生成填充_\n\n"
                "## 架构\n\n"
                "_待补充_\n"
            ),
        ),
    ],
)

# ---------- Research 项目 ----------

_RESEARCH_TEMPLATE = WikiTemplate(
    project_type="research",
    directories=[
        "wiki/literature",
        "wiki/experiments",
        "wiki/datasets",
        "wiki/methodology",
        "wiki/publications",
    ],
    pages=[
        WikiPageTemplate(
            relative_path="wiki/schema.md",
            title="Schema",
            content=(
                "# Schema\n\n"
                "科研项目的 Wiki 结构定义。\n\n"
                "## 目录结构\n\n"
                "- `raw/sources/` - 原始文献和数据（不可变）\n"
                "- `raw/assets/` - 附件资源（图表、数据集等）\n"
                "- `wiki/literature/` - 文献综述\n"
                "- `wiki/experiments/` - 实验记录\n"
                "- `wiki/datasets/` - 数据索引\n"
                "- `wiki/methodology/` - 方法论\n"
                "- `wiki/publications/` - 投稿追踪\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/overview.md",
            title="Overview",
            content=(
                "# {project_name}\n\n"
                "## 概述\n\n"
                "科研项目的 Wiki 知识库。\n\n"
                "## 页面\n\n"
                "- [文献综述](literature/) - 文献阅读笔记和综述\n"
                "- [实验记录](experiments/) - 实验方法、结果和分析\n"
                "- [数据索引](datasets/) - 数据集描述和来源\n"
                "- [方法论](methodology/) - 研究方法论\n"
                "- [投稿追踪](publications/) - 论文投稿和发表状态\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/index.md",
            title="Index",
            content=(
                "# Wiki 索引\n\n"
                "## 文献\n\n"
                "_待添加_\n\n"
                "## 实验\n\n"
                "_待添加_\n"
            ),
        ),
    ],
)

# ---------- Business 项目 ----------

_BUSINESS_TEMPLATE = WikiTemplate(
    project_type="business",
    directories=[
        "wiki/charter",
        "wiki/meetings",
        "wiki/deliverables",
        "wiki/timeline",
        "wiki/risks",
    ],
    pages=[
        WikiPageTemplate(
            relative_path="wiki/schema.md",
            title="Schema",
            content=(
                "# Schema\n\n"
                "事务项目的 Wiki 结构定义。\n\n"
                "## 目录结构\n\n"
                "- `raw/sources/` - 原始文档（不可变）\n"
                "- `raw/assets/` - 附件资源\n"
                "- `wiki/charter/` - 项目章程\n"
                "- `wiki/meetings/` - 会议纪要\n"
                "- `wiki/deliverables/` - 交付物清单\n"
                "- `wiki/timeline/` - 里程碑时间线\n"
                "- `wiki/risks/` - 风险登记册\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/overview.md",
            title="Overview",
            content=(
                "# {project_name}\n\n"
                "## 概述\n\n"
                "事务项目的 Wiki 知识库。\n\n"
                "## 页面\n\n"
                "- [项目章程](charter/) - 项目目标、范围和干系人\n"
                "- [会议纪要](meetings/) - 会议记录和决议\n"
                "- [交付物](deliverables/) - 交付物清单和状态\n"
                "- [里程碑](timeline/) - 项目时间线\n"
                "- [风险登记](risks/) - 风险识别和应对\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/index.md",
            title="Index",
            content=(
                "# Wiki 索引\n\n"
                "## 会议\n\n"
                "_待添加_\n\n"
                "## 交付物\n\n"
                "_待添加_\n"
            ),
        ),
    ],
)

# ---------- Personal 项目 ----------

_PERSONAL_TEMPLATE = WikiTemplate(
    project_type="personal",
    directories=[
        "wiki/inbox",
        "wiki/notes",
        "wiki/knowledge",
    ],
    pages=[
        WikiPageTemplate(
            relative_path="wiki/schema.md",
            title="Schema",
            content=(
                "# Schema\n\n"
                "个人项目的 Wiki 结构定义。\n\n"
                "## 目录结构\n\n"
                "- `raw/sources/` - 原始素材（不可变）\n"
                "- `raw/assets/` - 附件资源\n"
                "- `wiki/inbox/` - 收件箱（待整理）\n"
                "- `wiki/notes/` - 笔记\n"
                "- `wiki/knowledge/` - 知识库\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/overview.md",
            title="Overview",
            content=(
                "# {project_name}\n\n"
                "## 概述\n\n"
                "个人知识管理的 Wiki 空间。\n\n"
                "## 页面\n\n"
                "- [收件箱](inbox/) - 待整理的内容\n"
                "- [笔记](notes/) - 日常笔记\n"
                "- [知识库](knowledge/) - 结构化的知识\n"
            ),
        ),
        WikiPageTemplate(
            relative_path="wiki/index.md",
            title="Index",
            content=(
                "# Wiki 索引\n\n"
                "## 收件箱\n\n"
                "_待整理_\n\n"
                "## 笔记\n\n"
                "_待添加_\n"
            ),
        ),
    ],
)

# ---------- 模板注册表 ----------

TEMPLATES: Dict[str, WikiTemplate] = {
    "coding": _CODING_TEMPLATE,
    "research": _RESEARCH_TEMPLATE,
    "business": _BUSINESS_TEMPLATE,
    "personal": _PERSONAL_TEMPLATE,
}


def get_template(project_type: Optional[str]) -> WikiTemplate:
    """获取项目类型的 Wiki 模板。未知类型返回通用模板。"""
    if project_type and project_type in TEMPLATES:
        return TEMPLATES[project_type]
    # 通用 fallback: 使用 coding 模板作为默认
    return _CODING_TEMPLATE


def get_directories(project_type: Optional[str]) -> List[str]:
    """获取项目类型的所有目录（通用 + 类型专属）。"""
    template = get_template(project_type)
    return _COMMON_DIRECTORIES + template.directories


def get_pages(project_type: Optional[str], project_name: str = "Project") -> List[WikiPageTemplate]:
    """获取项目类型的所有页面模板（已替换变量）。"""
    template = get_template(project_type)
    pages: List[WikiPageTemplate] = []
    for page in _COMMON_PAGES + template.pages:
        pages.append(
            WikiPageTemplate(
                relative_path=page.relative_path,
                title=page.title,
                content=page.content.replace("{project_name}", project_name),
            )
        )
    return pages


def create_wiki_structure(
    project_path: Path,
    project_type: Optional[str] = None,
    project_name: Optional[str] = None,
    ensure_dir_fn=None,
    write_file_fn=None,
) -> None:
    """根据项目类型创建 Wiki 目录结构和初始页面。

    Args:
        project_path: 项目根目录
        project_type: 项目类型 (coding/research/business/personal)
        project_name: 项目名称（用于页面模板变量替换）
        ensure_dir_fn: 目录创建函数 (root, dir_path) -> None
        write_file_fn: 文件写入函数 (root, file_path, content) -> None
    """
    # 延迟导入避免循环依赖
    if ensure_dir_fn is None:
        from backend.wiki.files import secure_ensure_directory as _ensure
        ensure_dir_fn = _ensure
    if write_file_fn is None:
        from backend.wiki.files import secure_write_file_if_missing as _write
        write_file_fn = _write

    name = project_name or project_path.name
    directories = get_directories(project_type)
    pages = get_pages(project_type, name)

    # 创建目录
    for relative_dir in directories:
        ensure_dir_fn(project_path, project_path / relative_dir)

    # 创建页面
    for page in pages:
        file_path = project_path / page.relative_path
        write_file_fn(project_path, file_path, page.content)
