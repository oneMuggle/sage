"""多形态项目上下文预算水位与工作区资产台账探测服务 (2026-10-10)。

对应 docs/mcp-sage-project-management-organization-plan-20261010.md Phase P2：
1. 计算五层受控上下文水位（L1 SAGE.md / L2 Metadata+Constraints / L3 ProjectProfile / L4 Materials）；
2. 扫描项目工作区生成多态资产台账：
   - 一般档案 (business): 案卷文书成品台账 (.docx / .xlsx / .pptx / .pdf) 与四级目录归属；
   - 科研项目 (research): 文献库 (.bib / .pdf)、实验记录 (.ipynb / .py / .csv) 与论文手稿 (.tex / .docx)；
   - 代码工程 (coding): 工程构建/配置指示文件、SAGE.md 与 .sage/hooks.json 状态。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from backend.chat.project_context import (
    PER_FILE_CHAR_CAP,
    TOTAL_CHAR_CAP,
    build_constraints_block,
    build_project_materials_block,
    build_project_metadata_block,
    discover_project_context,
)
from backend.data.database import get_database
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_material_repo import ProjectMaterialRepository
from backend.data.project_repo import Project
from backend.memory.project_profile import ProjectProfileStore

logger = logging.getLogger(__name__)

OFFICE_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx", ".pdf", ".doc", ".xls", ".ppt"})
RESEARCH_EXTENSIONS = frozenset({".bib", ".tex", ".ipynb", ".pdf", ".csv", ".tsv", ".ris"})
CODING_INDICATOR_FILES = (
    "package.json",
    "pyproject.toml",
    "tsconfig.json",
    "Cargo.toml",
    "go.mod",
    "requirements.txt",
    "Makefile",
    "Dockerfile",
)
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        ".vite",
        "target",
        ".worktrees",
    }
)
MAX_SCANNED_FILES = 200


def inspect_project_context_budget(project: Project) -> Dict[str, Any]:
    """计算项目五层受控上下文的实时字符占用与水位比例。"""
    l1_block = discover_project_context(project.path).render()
    l2_meta_block = build_project_metadata_block(project)
    l2_constraints_block = build_constraints_block(project.id)

    m_repo = ProjectMaterialRepository()
    all_materials = m_repo.list_by_project(project.id)
    active_materials = m_repo.get_active_materials_for_project(project.id)
    l4_materials_block = build_project_materials_block(active_materials)

    c_repo = ProjectConstraintRepository()
    enabled_constraints = c_repo.list_by_project(project.id, enabled_only=True)

    l3_profile_chars = 0
    try:
        profile_store = ProjectProfileStore(get_database())
        profile_store.load()
        l3_profile_chars = len(profile_store.get_snapshot(project.path))
    except Exception as exc:  # noqa: BLE001
        logger.debug("inspect_project_context_budget profile skip: %s", exc)

    l1_chars = len(l1_block)
    l2_meta_chars = len(l2_meta_block)
    l2_constraints_chars = len(l2_constraints_block)
    l4_materials_chars = len(l4_materials_block)

    total_chars = (
        l1_chars + l2_meta_chars + l2_constraints_chars + l3_profile_chars + l4_materials_chars
    )
    cap_chars = TOTAL_CHAR_CAP
    usage_ratio = round(min(total_chars / float(cap_chars), 1.0), 4) if cap_chars > 0 else 0.0

    return {
        "project_id": project.id,
        "l1_conventions_chars": l1_chars,
        "l2_metadata_chars": l2_meta_chars,
        "l2_constraints_chars": l2_constraints_chars,
        "l3_profile_chars": l3_profile_chars,
        "l4_materials_chars": l4_materials_chars,
        "total_chars": total_chars,
        "cap_chars": cap_chars,
        "per_file_cap_chars": PER_FILE_CHAR_CAP,
        "usage_ratio": usage_ratio,
        "active_materials_count": len(active_materials),
        "total_materials_count": len(all_materials),
        "enabled_constraints_count": len(enabled_constraints),
    }


def _classify_dossier_stage(rel_path: str) -> str:
    top = rel_path.replace("\\", "/").split("/")[0]
    if top.startswith("00_") or "立项" in top or "需求" in top:
        return "立项与需求"
    if top.startswith("01_") or "参考" in top or "依据" in top or "法规" in top:
        return "参考依据"
    if top.startswith("02_") or "草稿" in top or "编制" in top:
        return "过程草稿"
    if top.startswith("03_") or "定稿" in top or "归档" in top or "签发" in top:
        return "定稿归档"
    return "根目录文书"


def _classify_research_stage(rel_path: str, ext: str) -> str:
    top = rel_path.replace("\\", "/").split("/")[0].lower()
    if "literature" in top or ext in (".bib", ".ris"):
        return "文献与引文库"
    if "experiment" in top or ext in (".ipynb", ".csv", ".tsv"):
        return "实验与数据集"
    if "manuscript" in top or ext == ".tex":
        return "论文手稿"
    if "submission" in top or "rebuttal" in top:
        return "投稿与审稿回复"
    return "科研文档"


def inspect_project_workspace_overview(project: Project) -> Dict[str, Any]:
    """只读扫描工作区顶层与一级子目录，输出多形态项目工作台所需的资产清单。"""
    root = Path(project.path)
    has_sage_md = False
    has_hooks_json = False
    coding_indicators: List[str] = []
    office_deliverables: List[Dict[str, Any]] = []
    research_artifacts: List[Dict[str, Any]] = []
    directory_summary: List[Dict[str, Any]] = []

    if not root.is_dir():
        return {
            "project_id": project.id,
            "has_sage_md": False,
            "has_hooks_json": False,
            "coding_indicators": [],
            "office_deliverables": [],
            "research_artifacts": [],
            "directory_summary": [],
        }

    for candidate in ("SAGE.md", "CLAUDE.md", "AGENTS.md"):
        if (root / candidate).is_file():
            has_sage_md = True
            break

    if (root / ".sage" / "hooks.json").is_file():
        has_hooks_json = True

    if (root / ".git").exists():
        coding_indicators.append(".git")
    for indicator in CODING_INDICATOR_FILES:
        if (root / indicator).is_file():
            coding_indicators.append(indicator)

    scanned = 0
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        entries = []

    for entry in entries:
        if scanned >= MAX_SCANNED_FILES:
            break
        name = entry.name
        if name in SKIP_DIRS or (name.startswith(".") and name != ".sage"):
            continue
        try:
            if entry.is_dir():
                sub_count = 0
                for child in sorted(entry.iterdir(), key=lambda p: p.name.lower()):
                    if child.name.startswith("."):
                        continue
                    if child.is_file():
                        sub_count += 1
                        if scanned < MAX_SCANNED_FILES:
                            scanned += 1
                            _collect_file_artifact(
                                root, child, office_deliverables, research_artifacts
                            )
                directory_summary.append({"name": name, "file_count": sub_count})
            elif entry.is_file():
                scanned += 1
                _collect_file_artifact(root, entry, office_deliverables, research_artifacts)
        except OSError:
            continue

    office_deliverables.sort(key=lambda item: item["modified_at"], reverse=True)
    research_artifacts.sort(key=lambda item: item["modified_at"], reverse=True)

    return {
        "project_id": project.id,
        "has_sage_md": has_sage_md,
        "has_hooks_json": has_hooks_json,
        "coding_indicators": coding_indicators,
        "office_deliverables": office_deliverables[:30],
        "research_artifacts": research_artifacts[:30],
        "directory_summary": directory_summary[:20],
    }


def _collect_file_artifact(
    root: Path,
    file_path: Path,
    office_deliverables: List[Dict[str, Any]],
    research_artifacts: List[Dict[str, Any]],
) -> None:
    ext = file_path.suffix.lower()
    if ext not in OFFICE_EXTENSIONS and ext not in RESEARCH_EXTENSIONS:
        return
    try:
        stat = file_path.stat()
        rel_path = os.path.relpath(str(file_path), str(root)).replace("\\", "/")
    except OSError:
        return

    base_info = {
        "name": file_path.name,
        "relative_path": rel_path,
        "ext": ext,
        "size_bytes": int(stat.st_size),
        "modified_at": int(stat.st_mtime * 1000),
    }
    if ext in OFFICE_EXTENSIONS:
        office_deliverables.append(
            {
                **base_info,
                "category": _classify_dossier_stage(rel_path),
            }
        )
    if ext in RESEARCH_EXTENSIONS:
        research_artifacts.append(
            {
                **base_info,
                "category": _classify_research_stage(rel_path, ext),
            }
        )


__all__ = [
    "inspect_project_context_budget",
    "inspect_project_workspace_overview",
]
