"""AI project bootstrap: preview and apply initialization suggestions.

2026-10-29. The preview is read-only (deterministic scan + optional LLM).
Apply is idempotent: SAGE.md is not overwritten unless explicitly asked,
rules are deduplicated by normalized content, milestones are only created
when the caller sends them, and ``git init`` runs only with explicit
consent and only when a git executable is available.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_material_repo import ProjectMaterialRepository
from backend.data.project_milestone_repo import ProjectMilestoneRepository
from backend.data.project_repo import Project, ProjectRepository
from backend.services.project_analysis_agent import ProjectAnalysisAgent
from backend.services.project_archetype_scaffold import get_archetype_blueprint
from backend.services.project_git_init import git_available, init_project_git
from backend.services.project_profiler import profile_project
from backend.services.project_rule_generator import ProjectRuleGenerator
from backend.services.project_wiki_generator import ProjectWikiGenerator
from backend.services.project_workspace_inspector import (
    create_project_checkpoint,
    write_project_charter,
)

logger = logging.getLogger(__name__)

MAX_RULES_PER_APPLY = 20
MAX_MILESTONES_PER_APPLY = 20
MAX_SAGE_MD_CHARS = 32_000


def _normalize(text: Optional[str]) -> str:
    """Normalize rule content for dedupe (whitespace + case insensitive)."""
    return " ".join((text or "").split()).lower()


def _rule_dict(
    *,
    key: str,
    label: str,
    content: str,
    reason: str,
    category: str,
    priority: int,
    trigger_pattern: str,
    source: str,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "content": content,
        "reason": reason,
        "category": category,
        "priority": priority,
        "trigger_pattern": trigger_pattern or "always",
        "source": source,
    }


def _collect_rules(
    report: Any,
    generated: Any,
    existing_contents: List[str],
) -> List[Dict[str, Any]]:
    seen = {_normalize(content) for content in existing_contents if content}
    rules: List[Dict[str, Any]] = []

    if generated is not None and getattr(generated, "rules", None):
        for rule in generated.rules:
            content = (rule.content or "").strip()
            key = _normalize(content)
            if not content or key in seen:
                continue
            seen.add(key)
            rules.append(
                _rule_dict(
                    key=rule.template_key or "ai_custom",
                    label=rule.template_key or "AI 专属规则",
                    content=content,
                    reason=rule.reason or "",
                    category=rule.category or "coding_style",
                    priority=rule.priority or 5,
                    trigger_pattern=rule.trigger_pattern or "always",
                    source=rule.source or "ai_custom",
                )
            )

    if not rules:
        for rule in getattr(report, "suggested_rules", []) or []:
            content = (rule.content or "").strip()
            key = _normalize(content)
            if not content or key in seen:
                continue
            seen.add(key)
            rules.append(
                _rule_dict(
                    key=rule.template_key or "ai_custom",
                    label=rule.label or rule.template_key or "推荐规则",
                    content=content,
                    reason=rule.reason or "",
                    category=rule.category or "coding_style",
                    priority=rule.priority or 5,
                    trigger_pattern=rule.trigger_pattern or "always",
                    source="template" if rule.template_key != "ai_custom" else "ai_custom",
                )
            )

    return rules[:10]


def _collect_milestones(
    generated: Any,
    project_type: Optional[str],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen: set = set()

    for milestone in getattr(generated, "milestones", None) or []:
        title = str(milestone.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            {
                "title": title,
                "description": milestone.get("description") or "",
                "stage": milestone.get("stage"),
                "estimated_days": milestone.get("estimated_days"),
            }
        )

    blueprint = get_archetype_blueprint(project_type)
    for milestone in blueprint.default_milestones:
        title = str(milestone.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        items.append(
            {
                "title": title,
                "description": milestone.get("description") or "",
                "stage": milestone.get("stage"),
                "estimated_days": None,
            }
        )

    return items[:8]


def _sage_md_draft(report: Any, project: Project) -> str:
    draft = (getattr(report, "sage_md_draft", "") or "").strip()
    if draft:
        return draft
    blueprint = get_archetype_blueprint(project.project_type)
    try:
        return blueprint.sage_md_template.format(project_name=project.name)
    except (KeyError, ValueError):
        return blueprint.sage_md_template


def _first_prompt(project_type: Optional[str]) -> str:
    if project_type == "coding":
        return "请先通读项目结构，总结技术栈、主要模块和关键入口，并指出下一步最值得做的事。"
    if project_type == "research":
        return "请先通读项目资料，总结研究问题、方法路径和已有证据，并指出下一步最值得推进的工作。"
    if project_type == "business":
        return "请先通览项目文档，总结当前进度、关键交付物和风险，并指出下一步最值得做的事。"
    return "请先了解这个项目，总结它的目标、现状和下一步最值得做的事。"


async def build_bootstrap_preview(
    project: Project,
    *,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Build a read-only initialization proposal for a project."""
    profile = profile_project(project.path)

    agent = ProjectAnalysisAgent()
    report = await agent.analyze(profile, allow_llm=use_llm)

    existing_constraints = ProjectConstraintRepository().list_by_project(project.id)
    existing_contents = [item.content for item in existing_constraints]

    generated = None
    if use_llm:
        try:
            generated = await ProjectRuleGenerator().generate(
                profile,
                report,
                existing_contents=existing_contents,
            )
        except Exception:  # LLM/parse failure must not break preview
            logger.warning("rule generation failed during bootstrap preview", exc_info=True)

    rules = _collect_rules(report, generated, existing_contents)
    milestones = _collect_milestones(generated, profile.level1_type)
    sage_md = _sage_md_draft(report, project)

    try:
        scanned = ProjectWikiGenerator().scan_files(
            project_root=project.path,
            allowed_paths=project.allowed_paths,
        )
    except Exception:
        logger.warning("wiki scan failed during bootstrap preview", exc_info=True)
        scanned = []

    language_counts: Dict[str, int] = {}
    for source_file in scanned:
        language_counts[source_file.language] = (
            language_counts.get(source_file.language, 0) + 1
        )

    git_stats = profile.git_stats.to_dict()
    has_git = git_available()
    root = Path(project.path)
    materials = ProjectMaterialRepository().list_by_project(project.id)
    milestones_count = len(ProjectMilestoneRepository().list_by_project(project.id))

    return {
        "project": project.to_dict(),
        "scan": {
            "level1_type": profile.level1_type,
            "sub_type": profile.sub_type,
            "tech_stack": list(profile.tech_stack),
            "frameworks": list(profile.frameworks),
            "source_files": [
                {"language": language, "count": count}
                for language, count in sorted(language_counts.items())
            ],
            "git": {**git_stats, "git_available": has_git},
            "existing": {
                "sage_md": (root / "SAGE.md").is_file(),
                "rules_count": len(existing_constraints),
                "milestones_count": milestones_count,
                "materials_count": len(materials),
            },
        },
        "suggestions": {
            "sage_md": {
                "content": sage_md,
                "rationale": getattr(report, "architecture_summary", "") or "",
                "exists": (root / "SAGE.md").is_file(),
            },
            "rules": rules,
            "milestones": milestones,
            "allowed_paths": [],
            "git_init": {
                "recommended": (not git_stats.get("is_repo", False)) and has_git,
                "reason": (
                    "检测到项目尚未纳入 Git，建议初始化仓库以便追踪变更"
                    if not git_stats.get("is_repo", False) and has_git
                    else (
                        "本机未检测到 Git，将使用内置快照"
                        if not has_git
                        else "项目已是 Git 仓库"
                    )
                ),
                "blockers": [] if has_git else ["git_not_available"],
            },
            "wiki": {
                "recommended": len(scanned) > 0,
                "estimated_pages": max(3, min(20, (len(scanned) + 11) // 12))
                if scanned
                else 0,
            },
            "first_prompt": _first_prompt(profile.level1_type),
        },
        "llm_available": bool(getattr(report, "llm_available", False) and use_llm),
    }


def _update_metadata(
    repo: ProjectRepository, project_id: str, metadata: Dict[str, Any]
) -> List[str]:
    applied: List[str] = []
    if "description" in metadata:
        repo.update_description(project_id, metadata.get("description"))
        applied.append("metadata.description")
    if "instructions" in metadata:
        repo.update_instructions(project_id, metadata.get("instructions"))
        applied.append("metadata.instructions")
    if "project_type" in metadata:
        repo.update_project_type(project_id, metadata.get("project_type"))
        applied.append("metadata.project_type")
    if "project_sub_type" in metadata:
        repo.update_project_sub_type(project_id, metadata.get("project_sub_type"))
        applied.append("metadata.project_sub_type")
    return applied


def apply_bootstrap(project: Project, accept: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a user-confirmed bootstrap plan. Idempotent per item."""
    repo = ProjectRepository()
    applied: List[str] = []
    skipped: List[str] = []
    errors: List[Dict[str, str]] = []
    git_result: Optional[Dict[str, Any]] = None

    metadata = accept.get("metadata") or {}
    if metadata:
        applied.extend(_update_metadata(repo, project.id, metadata))

    if accept.get("sage_md"):
        content = accept.get("sage_md_content")
        root = Path(project.path)
        if (root / "SAGE.md").exists() and not accept.get("overwrite_sage_md"):
            skipped.append("sage_md")
        else:
            try:
                write_project_charter(project, str(content or "")[:MAX_SAGE_MD_CHARS])
                applied.append("sage_md")
            except ValueError as exc:
                errors.append({"item": "sage_md", "message": str(exc)})

    constraint_repo = ProjectConstraintRepository()
    existing = {
        _normalize(item.content)
        for item in constraint_repo.list_by_project(project.id)
    }
    for rule in (accept.get("rules") or [])[:MAX_RULES_PER_APPLY]:
        content = str(rule.get("content") or "").strip()
        if not content:
            continue
        normalized = _normalize(content)
        if normalized in existing:
            skipped.append("rule")
            continue
        constraint_repo.create(
            project_id=project.id,
            category=str(rule.get("category") or "coding_style"),
            content=content,
            trigger_pattern=rule.get("trigger_pattern") or "always",
            priority=int(rule.get("priority") or 5),
        )
        existing.add(normalized)
        applied.append("rule")

    milestones = []
    for item in (accept.get("milestones") or [])[:MAX_MILESTONES_PER_APPLY]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        milestones.append(
            {
                "title": title,
                "description": item.get("description"),
                "stage": item.get("stage"),
                "estimated_days": item.get("estimated_days"),
            }
        )
    if milestones:
        ProjectMilestoneRepository().create_batch(project.id, milestones)
        applied.append("milestones")

    if accept.get("allowed_paths") is not None:
        repo.update_allowed_paths(project.id, list(accept.get("allowed_paths") or []))
        applied.append("allowed_paths")

    if accept.get("git_init"):
        if not git_available():
            errors.append({"item": "git_init", "message": "本机未检测到 Git，已跳过"})
        else:
            git_result = init_project_git(project.path)
            if git_result.get("initialized") or git_result.get("already_repo"):
                repo.update_vcs_mode(project.id, "git")
                applied.append("git_init")
            elif git_result.get("error"):
                errors.append({"item": "git_init", "message": str(git_result["error"])})

    if accept.get("initial_checkpoint"):
        try:
            create_project_checkpoint(project, "AI 初始化基线快照")
            applied.append("initial_checkpoint")
        except ValueError as exc:
            errors.append({"item": "initial_checkpoint", "message": str(exc)})

    previous: Dict[str, Any] = {}
    if project.bootstrap_state:
        try:
            previous = json.loads(project.bootstrap_state)
        except (TypeError, ValueError):
            previous = {}
    state = {
        **previous,
        "applied_at": int(time.time() * 1000),
        "applied": sorted(set(list(previous.get("applied") or []) + applied)),
    }
    repo.update_bootstrap_state(project.id, json.dumps(state, ensure_ascii=False))

    updated = repo.get(project.id) or project
    return {
        "project": updated.to_dict(),
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "git": git_result,
    }


__all__ = ["build_bootstrap_preview", "apply_bootstrap"]
