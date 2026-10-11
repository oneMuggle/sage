"""多形态项目上下文预算水位与工作区资产台账探测服务 (2026-10-10)。

对应 docs/mcp-sage-project-management-organization-plan-20261010.md Phase P2：
1. 计算五层受控上下文水位（L1 SAGE.md / L2 Metadata+Constraints / L3 ProjectProfile / L4 Materials）；
2. 扫描项目工作区生成多态资产台账：
   - 一般档案 (business): 案卷文书成品台账 (.docx / .xlsx / .pptx / .pdf) 与四级目录归属；
   - 科研项目 (research): 文献库 (.bib / .pdf)、实验记录 (.ipynb / .py / .csv) 与论文手稿 (.tex / .docx)；
   - 代码工程 (coding): 工程构建/配置指示文件、SAGE.md 与 .sage/hooks.json 状态。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
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
from backend.services.project_archetype_scaffold import get_archetype_blueprint

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
            "checkpoint_count": 0,
            "latest_checkpoint_at": None,
            "recent_checkpoints": [],
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

    checkpoint_count = 0
    latest_checkpoint_at = None
    recent_checkpoints: List[Dict[str, Any]] = []
    for cp_dir_name in ("checkpoints", "snapshots"):
        cp_dir = root / ".sage" / cp_dir_name
        if cp_dir.is_dir():
            try:
                for cp_item in cp_dir.iterdir():
                    if cp_item.name.startswith("."):
                        continue
                    checkpoint_count += 1
                    mtime_ms = int(cp_item.stat().st_mtime * 1000)
                    if latest_checkpoint_at is None or mtime_ms > latest_checkpoint_at:
                        latest_checkpoint_at = mtime_ms
                    cp_id = cp_item.stem
                    cp_label = cp_item.stem
                    cp_files = 0
                    if cp_item.is_file() and cp_item.suffix.lower() == ".json":
                        try:
                            raw_cp = json.loads(cp_item.read_text(encoding="utf-8", errors="ignore"))
                            if isinstance(raw_cp, dict):
                                cp_id = str(raw_cp.get("id") or cp_id)
                                cp_label = str(raw_cp.get("label") or cp_label)
                                cp_files = int(raw_cp.get("file_count") or 0)
                                mtime_ms = int(raw_cp.get("created_at") or mtime_ms)
                        except (OSError, ValueError, TypeError):
                            continue
                    recent_checkpoints.append(
                        {
                            "id": cp_id,
                            "label": cp_label,
                            "created_at": mtime_ms,
                            "file_count": cp_files,
                        }
                    )
            except OSError:
                pass
    recent_checkpoints.sort(key=lambda item: item["created_at"], reverse=True)

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
        "checkpoint_count": checkpoint_count,
        "latest_checkpoint_at": latest_checkpoint_at,
        "recent_checkpoints": recent_checkpoints[:10],
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


def extract_workspace_file_as_material_content(
    workspace_root: Path, relative_path: str
) -> str:
    """安全读取工作区内指定相对路径文件并提取为可注入受控资料池的文本。

    支持纯文本/代码/Markdown/BibTeX/LaTeX/CSV、Jupyter Notebook (.ipynb)
    以及 Office 文档 (.docx / .xlsx / .pptx) 的结构化文本提取。
    拒绝任何越界路径或符号链接逃逸。
    """
    clean_rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not clean_rel or ".." in clean_rel.split("/"):
        raise ValueError("非法的相对路径")

    root_real = Path(os.path.realpath(str(workspace_root)))
    candidate = root_real / clean_rel
    resolved = Path(os.path.realpath(str(candidate)))

    try:
        resolved.relative_to(root_real)
    except ValueError as exc:
        raise ValueError("文件路径越界，仅允许读取项目工作区内部文件") from exc

    if not resolved.is_file():
        raise FileNotFoundError(f"文件不存在: {clean_rel}")

    ext = resolved.suffix.lower()
    extracted = ""

    if ext == ".docx":
        try:
            import docx  # type: ignore[import-not-found]

            doc = docx.Document(str(resolved))
            paras = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
            extracted = "\n".join(paras)
        except Exception as exc:  # noqa: BLE001
            logger.debug("docx extract fallback for %s: %s", clean_rel, exc)
            extracted = f"[Word 文档: {clean_rel}, 大小: {resolved.stat().st_size} 字节]"
    elif ext == ".xlsx":
        try:
            import openpyxl  # type: ignore[import-not-found]

            wb = openpyxl.load_workbook(str(resolved), read_only=True, data_only=True)
            sheet_lines: List[str] = []
            for sheet_name in wb.sheetnames[:5]:
                ws = wb[sheet_name]
                sheet_lines.append(f"### 工作表: {sheet_name}")
                for row in list(ws.iter_rows(values_only=True))[:40]:
                    vals = [str(cell) if cell is not None else "" for cell in row]
                    if any(vals):
                        sheet_lines.append(" | ".join(vals))
            wb.close()
            extracted = "\n".join(sheet_lines)
        except Exception as exc:  # noqa: BLE001
            logger.debug("xlsx extract fallback for %s: %s", clean_rel, exc)
            extracted = f"[Excel 表格: {clean_rel}, 大小: {resolved.stat().st_size} 字节]"
    elif ext == ".pptx":
        try:
            import pptx  # type: ignore[import-not-found]

            prs = pptx.Presentation(str(resolved))
            slide_lines: List[str] = []
            for idx, slide in enumerate(prs.slides, start=1):
                texts = [
                    shape.text.strip()
                    for shape in slide.shapes
                    if getattr(shape, "has_text_frame", False) and shape.text.strip()
                ]
                if texts:
                    slide_lines.append(f"### Slide {idx}\n" + "\n".join(texts))
            extracted = "\n".join(slide_lines)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pptx extract fallback for %s: %s", clean_rel, exc)
            extracted = f"[PPT 演示文稿: {clean_rel}, 大小: {resolved.stat().st_size} 字节]"
    elif ext == ".ipynb":
        try:
            nb = json.loads(resolved.read_text(encoding="utf-8", errors="replace"))
            cell_lines: List[str] = []
            for cell in nb.get("cells", [])[:40]:
                ctype = cell.get("cell_type", "code")
                src = "".join(cell.get("source", [])).strip()
                if src:
                    cell_lines.append(f"[{ctype}]\n{src}")
            extracted = "\n\n".join(cell_lines)
        except Exception as exc:  # noqa: BLE001
            logger.debug("ipynb extract fallback for %s: %s", clean_rel, exc)
            extracted = resolved.read_text(encoding="utf-8", errors="replace")
    elif ext == ".pdf":
        extracted = f"[PDF 文献/案卷: {clean_rel}, 大小: {resolved.stat().st_size} 字节]"
    else:
        extracted = resolved.read_text(encoding="utf-8", errors="replace")

    body = (extracted or "").strip()
    if not body:
        body = f"[文件: {clean_rel}, 大小: {resolved.stat().st_size} 字节]"

    header = f"[来源文件: {clean_rel}]\n"
    max_body = max(PER_FILE_CHAR_CAP - len(header), 1000)
    if len(body) > max_body:
        body = body[:max_body] + "\n...[文件内容已按单资料预算截断]"
    return header + body


def inspect_project_runtime_and_hooks(project_id: str, workspace_root: str) -> Dict[str, Any]:
    """轻量只读诊断项目语言清单、本地运行时满足度、测试命令入口与 .sage/hooks.json 状态。"""
    root = Path(workspace_root)
    detected_languages: List[str] = []
    test_commands: List[str] = []
    recommendations: List[str] = []

    if root.exists() and root.is_dir():
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            detected_languages.append("TypeScript/Node.js" if (root / "tsconfig.json").is_file() else "Node.js")
            try:
                pkg_data = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
                scripts = pkg_data.get("scripts") or {}
                if isinstance(scripts, dict):
                    for key in ("test", "lint", "typecheck", "build", "dev"):
                        if key in scripts:
                            test_commands.append(f"npm run {key}")
            except Exception as exc:  # noqa: BLE001
                logger.debug("package.json parse skipped: %s", exc)

        if (root / "pyproject.toml").is_file() or (root / "requirements.txt").is_file() or (root / "pytest.ini").is_file():
            detected_languages.append("Python")
            test_commands.append("pytest")

        if (root / "Cargo.toml").is_file():
            detected_languages.append("Rust")
            test_commands.append("cargo test")

        if (root / "go.mod").is_file():
            detected_languages.append("Go")
            test_commands.append("go test ./...")

    available_runtimes: List[str] = []
    if sys.executable:
        available_runtimes.append("python")
    for bin_name in ("node", "git", "cargo", "go"):
        if shutil.which(bin_name):
            available_runtimes.append(bin_name)

    missing_runtimes: List[str] = []
    for lang in detected_languages:
        if "Node.js" in lang and "node" not in available_runtimes:
            missing_runtimes.append("node")
        if lang == "Rust" and "cargo" not in available_runtimes:
            missing_runtimes.append("cargo")
        if lang == "Go" and "go" not in available_runtimes:
            missing_runtimes.append("go")

    if missing_runtimes:
        level = "unsatisfied" if len(missing_runtimes) == len(detected_languages) else "partial"
        recommendations.append("缺少本地运行时: " + ", ".join(missing_runtimes))
    else:
        level = "satisfied"

    if not (root / "SAGE.md").is_file() and not (root / "CLAUDE.md").is_file() and not (root / "AGENTS.md").is_file():
        recommendations.append("建议生成 SAGE.md 声明构建/测试命令与模块边界")

    hooks_file = root / ".sage" / "hooks.json"
    hooks_config_exists = hooks_file.is_file()
    hooks_count = 0
    if hooks_config_exists:
        try:
            hooks_raw = json.loads(hooks_file.read_text(encoding="utf-8", errors="replace"))
            if isinstance(hooks_raw, dict):
                hooks_list = hooks_raw.get("hooks", hooks_raw)
                hooks_count = len(hooks_list) if isinstance(hooks_list, (list, dict)) else 1  # noqa: UP038
            elif isinstance(hooks_raw, list):
                hooks_count = len(hooks_raw)
        except Exception as exc:  # noqa: BLE001
            logger.debug("hooks.json parse skipped: %s", exc)

    hooks_trusted = False
    try:
        from backend.hooks.project_hooks import is_project_trusted  # type: ignore[import-not-found]

        hooks_trusted = bool(is_project_trusted(str(root)))
    except Exception:  # noqa: BLE001
        hooks_trusted = False

    return {
        "project_id": project_id,
        "level": level,
        "detected_languages": detected_languages,
        "available_runtimes": available_runtimes,
        "test_commands": test_commands[:6],
        "hooks_config_exists": hooks_config_exists,
        "hooks_count": hooks_count,
        "hooks_trusted": hooks_trusted,
        "recommendations": recommendations,
    }


def create_project_checkpoint(project: Project, label: str = "") -> Dict[str, Any]:
    """在项目工作区 .sage/checkpoints 下创建内置版本快照检查点记录。"""
    root = Path(project.path)
    if not root.is_dir():
        raise ValueError("项目目录不存在")
    overview = inspect_project_workspace_overview(project)
    now_ms = int(time.time() * 1000)
    cp_id = f"cp_{now_ms}"
    clean_label = (label or "").strip() or "工作区手动版本快照"
    tracked_files = [
        item["relative_path"]
        for item in (
            overview.get("office_deliverables", []) + overview.get("research_artifacts", [])
        )
    ]
    if (root / "SAGE.md").is_file():
        tracked_files.insert(0, "SAGE.md")
    try:
        for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                continue
            if entry.is_file() and entry.suffix.lower() in {".md", ".txt"}:
                if entry.name not in tracked_files:
                    tracked_files.append(entry.name)
            elif entry.is_dir():
                for child in sorted(entry.iterdir(), key=lambda item: item.name.lower()):
                    if child.is_file() and child.suffix.lower() in {".md", ".txt"}:
                        rel_child = f"{entry.name}/{child.name}"
                        if rel_child not in tracked_files:
                            tracked_files.append(rel_child)
    except OSError:
        pass
    snapshots: Dict[str, str] = {}
    text_exts = {".md", ".tex", ".bib", ".txt", ".json", ".csv"}
    for rel_path in tracked_files[:20]:
        candidate = (root / rel_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        if candidate.is_file() and candidate.suffix.lower() in text_exts:
            try:
                if candidate.stat().st_size <= 32768:
                    snapshots[rel_path] = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    cp_dir = root / ".sage" / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": cp_id,
        "project_id": project.id,
        "label": clean_label,
        "created_at": now_ms,
        "file_count": len(tracked_files),
        "files": tracked_files[:50],
        "snapshots": snapshots,
    }
    (cp_dir / f"{cp_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "id": cp_id,
        "label": clean_label,
        "created_at": now_ms,
        "file_count": len(tracked_files),
    }


def restore_project_checkpoint(project: Project, checkpoint_id: str) -> Dict[str, Any]:
    """从项目工作区 .sage/checkpoints 还原指定版本快照中的文本与规范文件。"""
    root = Path(project.path)
    if not root.is_dir():
        raise ValueError("项目目录不存在")
    clean_cid = (checkpoint_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", clean_cid):
        raise ValueError("无效的检查点 ID")
    cp_file = root / ".sage" / "checkpoints" / f"{clean_cid}.json"
    if not cp_file.is_file():
        raise FileNotFoundError(f"检查点不存在: {clean_cid}")
    try:
        raw_cp = json.loads(cp_file.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("检查点元数据损坏") from exc
    if not isinstance(raw_cp, dict):
        raise ValueError("检查点格式无效")
    snapshots = raw_cp.get("snapshots")
    restored_files: List[str] = []
    root_resolved = root.resolve()
    if isinstance(snapshots, dict):
        for rel_path, content in snapshots.items():
            if not isinstance(rel_path, str) or not isinstance(content, str):
                continue
            target = (root_resolved / rel_path).resolve()
            try:
                target.relative_to(root_resolved)
            except ValueError:
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                restored_files.append(rel_path)
            except OSError:
                continue
    now_ms = int(time.time() * 1000)
    return {
        "id": str(raw_cp.get("id") or clean_cid),
        "label": str(raw_cp.get("label") or clean_cid),
        "restored_files": restored_files,
        "restored_at": now_ms,
    }


def read_project_charter(project: Project) -> Dict[str, Any]:
    """读取项目工作区 L1 本地规范文件 SAGE.md 及其形态化推荐模板。"""
    root = Path(project.path)
    blueprint = get_archetype_blueprint(project.project_type)
    recommended_template = blueprint.sage_md_template.format(project_name=project.name or root.name or "Project")
    sage_md = root / "SAGE.md"
    exists = sage_md.is_file()
    content = ""
    if exists:
        try:
            content = sage_md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            content = ""
    return {
        "project_id": project.id,
        "exists": exists,
        "content": content,
        "char_count": len(content),
        "recommended_template": recommended_template,
    }


def write_project_charter(project: Project, content: str) -> Dict[str, Any]:
    """写入并保存项目工作区 L1 本地规范文件 SAGE.md。"""
    root = Path(project.path)
    if not root.is_dir():
        raise ValueError("项目目录不存在")
    clean_content = content if isinstance(content, str) else ""
    if len(clean_content) > 32000:
        raise ValueError("SAGE.md 内容超出最大长度限制 (32000 字符)")
    root_resolved = root.resolve()
    target = (root_resolved / "SAGE.md").resolve()
    target.relative_to(root_resolved)
    try:
        target.write_text(clean_content, encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"写入 SAGE.md 失败: {exc}") from exc
    return read_project_charter(project)


def get_project_checkpoint_detail(project: Project, checkpoint_id: str) -> Dict[str, Any]:
    """读取指定内置版本控制检查点的文件清单与文本快照详情。"""
    root = Path(project.path)
    if not root.is_dir():
        raise ValueError("项目目录不存在")
    clean_cid = (checkpoint_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", clean_cid):
        raise ValueError("无效的检查点 ID")
    cp_file = root / ".sage" / "checkpoints" / f"{clean_cid}.json"
    if not cp_file.is_file():
        raise FileNotFoundError(f"检查点不存在: {clean_cid}")
    try:
        raw_cp = json.loads(cp_file.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("检查点元数据损坏") from exc
    if not isinstance(raw_cp, dict):
        raise ValueError("检查点格式无效")
    raw_files = raw_cp.get("files")
    files = [str(f) for f in raw_files if isinstance(f, str)] if isinstance(raw_files, list) else []
    raw_snaps = raw_cp.get("snapshots")
    snapshots: Dict[str, str] = {}
    if isinstance(raw_snaps, dict):
        for k, v in raw_snaps.items():
            if isinstance(k, str) and isinstance(v, str):
                snapshots[k] = v
    return {
        "id": str(raw_cp.get("id") or clean_cid),
        "label": str(raw_cp.get("label") or clean_cid),
        "created_at": int(raw_cp.get("created_at") or 0),
        "file_count": int(raw_cp.get("file_count") or len(files)),
        "files": files,
        "snapshots": snapshots,
    }
