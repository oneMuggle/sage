"""Per-item diff between playbook specs for import preview (2026-11-01).

The top-level keys (``stages_added`` / ``stages_removed`` / ``stages_changed`` /
``directories_added`` / ``directories_removed`` / ``name_changed`` /
``description_changed``) are kept for backwards compatibility. ``stage_details``
adds artifact / rule / milestone / exit-criteria level changes so users can see
exactly what an import will alter before choosing a conflict strategy.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

MAX_LISTED_ITEMS = 20
ARTIFACT_FIELDS = (
    "label",
    "required",
    "required_when",
    "target_dir",
    "match",
    "content_checks",
    "missing_action",
)
CRITERION_FIELDS = ("label", "type", "artifact_id")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _by_id(items: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            indexed[str(item["id"])] = item
    return indexed


def _rule_label(rule: Any) -> str:
    if not isinstance(rule, dict):
        return str(rule)[:60]
    content = str(rule.get("content") or "").strip()
    if content:
        return content[:60]
    template_key = str(rule.get("template_key") or "").strip()
    return "template:" + template_key if template_key else "规则"


def _rule_index(rules: Iterable[Any]) -> Dict[str, str]:
    indexed: Dict[str, str] = {}
    for rule in rules or []:
        indexed[_canonical(rule)] = _rule_label(rule)
    return indexed


def _milestone_index(milestones: Iterable[Any]) -> Dict[str, str]:
    indexed: Dict[str, str] = {}
    for milestone in milestones or []:
        if isinstance(milestone, dict):
            title = str(milestone.get("title") or "").strip() or "里程碑"
        else:
            title = str(milestone)[:60]
        indexed[_canonical(milestone)] = title
    return indexed


def _diff_stage(old_stage: Dict[str, Any], new_stage: Dict[str, Any]) -> Dict[str, Any]:
    old_artifacts = _by_id(old_stage.get("artifacts") or [])
    new_artifacts = _by_id(new_stage.get("artifacts") or [])
    artifacts_added = [
        {"id": item_id, "label": new_artifacts[item_id].get("label") or item_id}
        for item_id in sorted(set(new_artifacts) - set(old_artifacts))
    ]
    artifacts_removed = [
        {"id": item_id, "label": old_artifacts[item_id].get("label") or item_id}
        for item_id in sorted(set(old_artifacts) - set(new_artifacts))
    ]
    artifacts_changed: List[Dict[str, Any]] = []
    for item_id in sorted(set(old_artifacts) & set(new_artifacts)):
        old_item = old_artifacts[item_id]
        new_item = new_artifacts[item_id]
        fields = [
            field for field in ARTIFACT_FIELDS if old_item.get(field) != new_item.get(field)
        ]
        if fields:
            artifacts_changed.append(
                {
                    "id": item_id,
                    "label": new_item.get("label") or item_id,
                    "fields": fields,
                }
            )

    old_criteria = _by_id(old_stage.get("exit_criteria") or [])
    new_criteria = _by_id(new_stage.get("exit_criteria") or [])
    criteria_added = [
        {"id": item_id, "label": new_criteria[item_id].get("label") or item_id}
        for item_id in sorted(set(new_criteria) - set(old_criteria))
    ]
    criteria_removed = [
        {"id": item_id, "label": old_criteria[item_id].get("label") or item_id}
        for item_id in sorted(set(old_criteria) - set(new_criteria))
    ]
    criteria_changed: List[Dict[str, Any]] = []
    for item_id in sorted(set(old_criteria) & set(new_criteria)):
        old_item = old_criteria[item_id]
        new_item = new_criteria[item_id]
        fields = [
            field for field in CRITERION_FIELDS if old_item.get(field) != new_item.get(field)
        ]
        if fields:
            criteria_changed.append(
                {
                    "id": item_id,
                    "label": new_item.get("label") or item_id,
                    "fields": fields,
                }
            )

    old_rules = _rule_index(old_stage.get("rules") or [])
    new_rules = _rule_index(new_stage.get("rules") or [])
    rules_added = [label for key, label in new_rules.items() if key not in old_rules]
    rules_removed = [label for key, label in old_rules.items() if key not in new_rules]

    old_milestones = _milestone_index(old_stage.get("recommended_milestones") or [])
    new_milestones = _milestone_index(new_stage.get("recommended_milestones") or [])
    milestones_added = [
        title for key, title in new_milestones.items() if key not in old_milestones
    ]
    milestones_removed = [
        title for key, title in old_milestones.items() if key not in new_milestones
    ]

    changed_fields = [
        field
        for field in ("label", "objective", "order")
        if old_stage.get(field) != new_stage.get(field)
    ]
    details: Dict[str, Any] = {
        "label": new_stage.get("label") or old_stage.get("label") or "",
        "changed_fields": changed_fields,
        "artifacts_added": artifacts_added[:MAX_LISTED_ITEMS],
        "artifacts_removed": artifacts_removed[:MAX_LISTED_ITEMS],
        "artifacts_changed": artifacts_changed[:MAX_LISTED_ITEMS],
        "rules_added": rules_added[:MAX_LISTED_ITEMS],
        "rules_removed": rules_removed[:MAX_LISTED_ITEMS],
        "milestones_added": milestones_added[:MAX_LISTED_ITEMS],
        "milestones_removed": milestones_removed[:MAX_LISTED_ITEMS],
        "criteria_added": criteria_added[:MAX_LISTED_ITEMS],
        "criteria_removed": criteria_removed[:MAX_LISTED_ITEMS],
        "criteria_changed": criteria_changed[:MAX_LISTED_ITEMS],
    }
    details["has_changes"] = bool(
        changed_fields
        or details["artifacts_added"]
        or details["artifacts_removed"]
        or details["artifacts_changed"]
        or details["rules_added"]
        or details["rules_removed"]
        or details["milestones_added"]
        or details["milestones_removed"]
        or details["criteria_added"]
        or details["criteria_removed"]
        or details["criteria_changed"]
    )
    return details


def _directory_index(layout: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for entry in layout or []:
        if isinstance(entry, dict) and entry.get("path"):
            indexed[str(entry["path"])] = entry
    return indexed


def diff_playbooks(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Return a per-item diff from ``old`` to ``new`` playbook specs."""
    old_stages = _by_id(old.get("stages") or [])
    new_stages = _by_id(new.get("stages") or [])

    stage_details: Dict[str, Any] = {}
    for stage_id in sorted(set(old_stages) & set(new_stages)):
        details = _diff_stage(old_stages[stage_id], new_stages[stage_id])
        if details["has_changes"]:
            stage_details[stage_id] = details

    old_dirs = _directory_index(old.get("directory_layout") or [])
    new_dirs = _directory_index(new.get("directory_layout") or [])
    directories_changed = [
        path
        for path in sorted(set(old_dirs) & set(new_dirs))
        if old_dirs[path] != new_dirs[path]
    ]

    old_rules = _rule_index(old.get("global_rules") or [])
    new_rules = _rule_index(new.get("global_rules") or [])

    return {
        "stages_added": sorted(set(new_stages) - set(old_stages)),
        "stages_removed": sorted(set(old_stages) - set(new_stages)),
        "stages_changed": sorted(stage_details),
        "directories_added": sorted(set(new_dirs) - set(old_dirs)),
        "directories_removed": sorted(set(old_dirs) - set(new_dirs)),
        "directories_changed": directories_changed,
        "name_changed": old.get("name") != new.get("name"),
        "description_changed": old.get("description") != new.get("description"),
        "global_rules_added": [
            label for key, label in new_rules.items() if key not in old_rules
        ][:MAX_LISTED_ITEMS],
        "global_rules_removed": [
            label for key, label in old_rules.items() if key not in new_rules
        ][:MAX_LISTED_ITEMS],
        "stage_details": stage_details,
    }


__all__ = ["diff_playbooks"]
