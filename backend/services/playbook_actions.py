"""Execute user-approved playbook actions (2026-10-31).

All actions are idempotent and confined to the project root. A checkpoint is
created before the first write, and files that already exist are never
overwritten. Actions are always previewed by the caller before this module runs.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.data.playbook_repo import PlaybookRepository
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_milestone_repo import ProjectMilestoneRepository
from backend.data.project_repo import ProjectRepository
from backend.services.playbook_library import render_doc_stub
from backend.services.project_workspace_inspector import create_project_checkpoint

logger = logging.getLogger(__name__)

MAX_ACTIONS_PER_APPLY = 50
MAX_RULES_PER_ACTION = 30
MAX_MILESTONES_PER_ACTION = 30
MAX_STAGE_HISTORY = 100


def _normalize(text: Optional[str]) -> str:
    return " ".join((text or "").split()).lower()


def _safe_target(root: Path, relative: Any) -> Path:
    raw = str(relative if relative is not None else "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or raw.startswith("~"):
        raise ValueError("非法路径: %r" % raw)
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("非法路径: %r" % raw)
    root_resolved = root.resolve()
    target = (root_resolved / "/".join(parts)).resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("路径越界: %r" % raw)
    return target


def _create_folder(root: Path, payload: Dict[str, Any]) -> str:
    target = _safe_target(root, payload.get("path"))
    if target.exists():
        return "skipped"
    target.mkdir(parents=True, exist_ok=True)
    return "applied"


def _create_doc_stub(root: Path, payload: Dict[str, Any]) -> str:
    target = _safe_target(root, payload.get("path"))
    if target.exists():
        return "skipped"
    if target.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("文档骨架目前只支持 .md / .txt: %s" % target.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    title = payload.get("title")
    content = render_doc_stub(payload.get("template"), title=title)
    target.write_text(content, encoding="utf-8")
    return "applied"


def _apply_rules(project_id: str, payload: Dict[str, Any]) -> str:
    rules = payload.get("rules") or []
    if not isinstance(rules, list) or not rules:
        raise ValueError("apply_rules 需要 rules 数组")
    repo = ProjectConstraintRepository()
    existing = {_normalize(item.content) for item in repo.list_by_project(project_id)}
    created = 0
    for rule in rules[:MAX_RULES_PER_ACTION]:
        if not isinstance(rule, dict):
            continue
        content = str(rule.get("content") or "").strip()
        if not content:
            continue
        normalized = _normalize(content)
        if normalized in existing:
            continue
        repo.create(
            project_id=project_id,
            category=str(rule.get("category") or "coding_style"),
            content=content,
            trigger_pattern=rule.get("trigger_pattern") or "always",
            priority=int(rule.get("priority") or 5),
        )
        existing.add(normalized)
        created += 1
    return "applied" if created else "skipped"


def _seed_milestones(project_id: str, payload: Dict[str, Any]) -> str:
    milestones = payload.get("milestones") or []
    if not isinstance(milestones, list) or not milestones:
        raise ValueError("seed_milestones 需要 milestones 数组")
    repo = ProjectMilestoneRepository()
    existing = {
        (item.title, item.stage or None) for item in repo.list_by_project(project_id)
    }
    to_create: List[Dict[str, Any]] = []
    for index, item in enumerate(milestones[:MAX_MILESTONES_PER_ACTION]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        stage = item.get("stage") or None
        if not title or (title, stage) in existing:
            continue
        existing.add((title, stage))
        to_create.append(
            {
                "title": title,
                "description": item.get("description") or "",
                "stage": stage,
                "sort_order": index + 1,
                "estimated_days": item.get("estimated_days"),
            }
        )
    if not to_create:
        return "skipped"
    repo.create_batch(project_id, to_create)
    return "applied"


def _set_stage(project: Any, payload: Dict[str, Any]) -> str:
    stage_id = str(payload.get("stage_id") or "").strip()
    if not stage_id:
        raise ValueError("set_stage 需要 stage_id")
    repo = PlaybookRepository()
    state = repo.get_state(project.id)
    previous = state.get("current_stage")
    history = list(state.get("stage_history") or [])
    history.append(
        {
            "from": previous,
            "to": stage_id,
            "at": int(time.time() * 1000),
            "source": "user",
        }
    )
    state["current_stage"] = stage_id
    state["stage_history"] = history[-MAX_STAGE_HISTORY:]
    ProjectRepository().update_project_stage(project.id, stage_id)
    repo.update_state(project.id, state)
    return "applied"


def apply_playbook_actions(project: Any, actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute a user-approved action list.

    Args:
        project: project object with ``id`` and ``path``.
        actions: list of ``{"type": ..., "payload": {...}}`` items.

    Returns:
        ``{applied, skipped, errors, checkpoint_created}``.
    """
    applied: List[str] = []
    skipped: List[str] = []
    errors: List[Dict[str, str]] = []
    root = Path(getattr(project, "path", ""))
    if not root.is_dir():
        return {
            "applied": [],
            "skipped": [],
            "errors": [{"item": "project", "message": "项目目录不存在"}],
            "checkpoint_created": False,
        }

    checkpoint_created = False
    if actions:
        try:
            create_project_checkpoint(project, "应用项目规程")
            checkpoint_created = True
        except Exception:  # noqa: BLE001 — checkpoint failure must not block actions
            logger.warning("failed to create checkpoint before playbook actions", exc_info=True)

    for action in actions[:MAX_ACTIONS_PER_APPLY]:
        if not isinstance(action, dict):
            errors.append({"item": "unknown", "message": "动作必须是对象"})
            continue
        action_type = str(action.get("type") or "").strip()
        payload = action.get("payload") or {}
        if not isinstance(payload, dict):
            errors.append({"item": action_type or "unknown", "message": "payload 必须是对象"})
            continue
        try:
            if action_type == "create_folder":
                outcome = _create_folder(root, payload)
            elif action_type == "create_doc_stub":
                outcome = _create_doc_stub(root, payload)
            elif action_type == "apply_rules":
                outcome = _apply_rules(project.id, payload)
            elif action_type == "seed_milestones":
                outcome = _seed_milestones(project.id, payload)
            elif action_type == "set_stage":
                outcome = _set_stage(project, payload)
            else:
                errors.append({"item": action_type or "unknown", "message": "不支持的动作类型"})
                continue
            if outcome == "applied":
                applied.append(action_type)
            else:
                skipped.append(action_type)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append({"item": action_type or "unknown", "message": str(exc)})

    return {
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "checkpoint_created": checkpoint_created,
    }


__all__ = ["apply_playbook_actions"]
