"""Project playbook spec: validation, normalization, hashing (2026-10-31).

A playbook is a versioned JSON document that describes a project-management
methodology: directory layout, stage pipeline, per-stage artifact requirements,
exit criteria, rules, recommended milestones and AI guidance.

This module is intentionally dependency-free (standard library only) so the
same code can run on the Win7 / Python 3.8 branch.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

PLAYBOOK_SCHEMA_VERSION = "1.0"
MAX_STAGES = 20
MAX_ARTIFACTS_PER_STAGE = 50
MAX_GLOBS_PER_ARTIFACT = 20
MAX_STAGE_RULES = 50
MAX_GLOBAL_RULES = 100

_PROJECT_TYPES = {"coding", "research", "business", "personal"}
_MISSING_ACTION_TYPES = {
    "create_folder",
    "create_doc_stub",
    "apply_rules",
    "seed_milestones",
    "add_todo",
    "open_doc",
    "move_file",
}
_CONTENT_CHECK_TYPES = {"keyword", "keyword_or_llm", "llm", "manual"}


class PlaybookValidationError(ValueError):
    """Raised when a playbook document is malformed or unsafe."""


def is_compatible(version: str) -> bool:
    """Return True when the major schema version matches this implementation."""
    major = str(version or "").split(".", 1)[0].strip()
    return major.isdigit() and major == PLAYBOOK_SCHEMA_VERSION.split(".", 1)[0]


def _text(value: Any, field: str, *, required: bool = False, max_len: int = 4000) -> str:
    text = str(value if value is not None else "").strip()
    if required and not text:
        raise PlaybookValidationError(f"缺少字段: {field}")
    if len(text) > max_len:
        raise PlaybookValidationError(f"字段 {field} 超长")
    return text


def _rel_path(value: Any, field: str) -> str:
    raw = _text(value, field, required=True, max_len=1024).replace("\\", "/")
    if raw.startswith("/") or raw.startswith("~"):
        raise PlaybookValidationError(f"非法相对路径: {raw!r}")
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise PlaybookValidationError(f"非法相对路径: {raw!r}")
    return "/".join(parts)


def _positive_int(value: Any, field: str, default: int) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PlaybookValidationError(f"字段 {field} 必须是整数") from exc
    if number < 0:
        raise PlaybookValidationError(f"字段 {field} 不能为负数")
    return number


def _bool(value: Any, default: bool) -> bool:
    return default if value is None else bool(value)


def _normalize_artifact(raw: Dict[str, Any], stage_id: str, index: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlaybookValidationError("产物定义必须是对象")
    artifact_id = _text(raw.get("id"), "artifacts.id", required=True, max_len=128)
    label = _text(raw.get("label"), "artifacts.label", required=True, max_len=200)
    match = raw.get("match") or {}
    if not isinstance(match, dict):
        raise PlaybookValidationError(f"产物 {artifact_id} 的 match 必须是对象")
    globs: List[str] = []
    for glob in (match.get("globs") or [])[:MAX_GLOBS_PER_ARTIFACT]:
        normalized = _text(glob, "match.globs", required=True, max_len=1024).replace("\\", "/")
        globs.append(normalized)
    if not globs:
        raise PlaybookValidationError(f"产物 {artifact_id} 缺少 match.globs")

    max_age_days = match.get("max_age_days")
    if max_age_days is not None:
        try:
            max_age_days = int(max_age_days)
        except (TypeError, ValueError) as exc:
            raise PlaybookValidationError(
                f"产物 {artifact_id} 的 max_age_days 必须是整数"
            ) from exc
        if max_age_days <= 0:
            raise PlaybookValidationError(
                f"产物 {artifact_id} 的 max_age_days 必须大于 0"
            )

    checks: List[Dict[str, Any]] = []
    for check in raw.get("content_checks") or []:
        if not isinstance(check, dict):
            raise PlaybookValidationError("content_checks 必须是对象数组")
        check_type = _text(check.get("type"), "content_checks.type", required=True, max_len=32)
        if check_type not in _CONTENT_CHECK_TYPES:
            raise PlaybookValidationError(f"不支持的 content_check 类型: {check_type}")
        checks.append(
            {
                "id": _text(check.get("id"), "content_checks.id", required=True, max_len=128),
                "label": _text(check.get("label"), "content_checks.label", required=True, max_len=200),
                "type": check_type,
                "keywords": [
                    _text(item, "content_checks.keywords", max_len=100)
                    for item in (check.get("keywords") or [])
                ],
                "llm_prompt": _text(check.get("llm_prompt"), "content_checks.llm_prompt", max_len=4000),
            }
        )

    missing_action = raw.get("missing_action")
    if missing_action is not None:
        if not isinstance(missing_action, dict):
            raise PlaybookValidationError("missing_action 必须是对象")
        action_type = _text(
            missing_action.get("type"), "missing_action.type", required=True, max_len=32
        )
        if action_type not in _MISSING_ACTION_TYPES:
            raise PlaybookValidationError(f"不支持的 missing_action: {action_type}")
        payload = missing_action.get("payload") or {}
        if not isinstance(payload, dict):
            raise PlaybookValidationError("missing_action.payload 必须是对象")
        missing_action = {"type": action_type, "payload": dict(payload)}

    return {
        "id": artifact_id,
        "label": label,
        "required": _bool(raw.get("required"), True),
        "required_when": _text(raw.get("required_when"), "required_when", max_len=200) or None,
        "target_dir": (
            _rel_path(raw.get("target_dir"), "target_dir")
            if raw.get("target_dir")
            else None
        ),
        "match": {
            "globs": globs,
            "min_bytes": _positive_int(match.get("min_bytes"), "match.min_bytes", 0),
            "min_count": max(1, _positive_int(match.get("min_count"), "match.min_count", 1)),
            "max_age_days": max_age_days,
        },
        "content_checks": checks,
        "missing_action": missing_action,
    }


def _normalize_stage(raw: Dict[str, Any], fallback_order: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlaybookValidationError("阶段定义必须是对象")
    stage_id = _text(raw.get("id"), "stages.id", required=True, max_len=128)
    label = _text(raw.get("label"), "stages.label", required=True, max_len=200)
    try:
        order = int(raw.get("order") or fallback_order)
    except (TypeError, ValueError) as exc:
        raise PlaybookValidationError(f"阶段 {stage_id} 的 order 必须是整数") from exc

    artifacts: List[Dict[str, Any]] = []
    seen_artifacts = set()
    for index, artifact in enumerate((raw.get("artifacts") or [])[:MAX_ARTIFACTS_PER_STAGE]):
        normalized = _normalize_artifact(artifact, stage_id, index)
        if normalized["id"] in seen_artifacts:
            raise PlaybookValidationError("阶段 {} 的产物 id 重复: {}".format(stage_id, normalized["id"]))
        seen_artifacts.add(normalized["id"])
        artifacts.append(normalized)

    rules = [dict(item) for item in (raw.get("rules") or [])[:MAX_STAGE_RULES] if isinstance(item, dict)]
    milestones = [
        dict(item) for item in (raw.get("recommended_milestones") or []) if isinstance(item, dict)
    ]
    exit_criteria = [
        dict(item) for item in (raw.get("exit_criteria") or []) if isinstance(item, dict)
    ]

    return {
        "id": stage_id,
        "label": label,
        "order": order,
        "objective": _text(raw.get("objective"), "stages.objective", max_len=2000),
        "artifacts": artifacts,
        "exit_criteria": exit_criteria,
        "rules": rules,
        "recommended_milestones": milestones,
    }


def normalize_playbook(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and canonicalize a playbook document.

    Raises:
        PlaybookValidationError: for unknown schema versions, missing fields,
            unsafe paths, duplicate stage/artifact ids, or malformed entries.
    """
    if not isinstance(raw, dict):
        raise PlaybookValidationError("规程必须是 JSON 对象")

    version = str(raw.get("schema_version") or "")
    if not is_compatible(version):
        raise PlaybookValidationError(f"不兼容的 schema_version: {version}")

    playbook_id = _text(raw.get("id"), "id", required=True, max_len=128)
    name = _text(raw.get("name"), "name", required=True, max_len=200)
    stages_raw = raw.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise PlaybookValidationError("缺少字段: stages")
    if len(stages_raw) > MAX_STAGES:
        raise PlaybookValidationError("阶段数量超限")

    applies_to = raw.get("applies_to") or {}
    if not isinstance(applies_to, dict):
        raise PlaybookValidationError("applies_to 必须是对象")
    project_types = [
        _text(item, "applies_to.project_types", max_len=32)
        for item in (applies_to.get("project_types") or [])
    ]
    unknown_types = [item for item in project_types if item not in _PROJECT_TYPES]
    if unknown_types:
        raise PlaybookValidationError("未知项目类型: {}".format(", ".join(unknown_types)))

    directories: List[Dict[str, Any]] = []
    seen_paths = set()
    for item in raw.get("directory_layout") or []:
        if not isinstance(item, dict):
            raise PlaybookValidationError("directory_layout 必须是对象数组")
        path = _rel_path(item.get("path"), "directory_layout.path")
        if path in seen_paths:
            raise PlaybookValidationError(f"目录重复: {path}")
        seen_paths.add(path)
        directories.append(
            {
                "path": path,
                "required": _bool(item.get("required"), True),
                "purpose": _text(item.get("purpose"), "directory_layout.purpose", max_len=500),
            }
        )

    stages: List[Dict[str, Any]] = []
    seen_stages = set()
    for index, stage in enumerate(stages_raw, start=1):
        normalized = _normalize_stage(stage, index)
        if normalized["id"] in seen_stages:
            raise PlaybookValidationError("阶段 id 重复: {}".format(normalized["id"]))
        seen_stages.add(normalized["id"])
        stages.append(normalized)
    stages.sort(key=lambda item: (item["order"], item["id"]))

    return {
        "schema_version": PLAYBOOK_SCHEMA_VERSION,
        "id": playbook_id,
        "name": name,
        "description": _text(raw.get("description"), "description", max_len=4000),
        "applies_to": {
            "project_types": project_types,
            "sub_types": [
                _text(item, "applies_to.sub_types", max_len=64)
                for item in (applies_to.get("sub_types") or [])
            ],
        },
        "directory_layout": directories,
        "stages": stages,
        "global_rules": [
            dict(item) for item in (raw.get("global_rules") or [])[:MAX_GLOBAL_RULES] if isinstance(item, dict)
        ],
        "todos": [dict(item) for item in (raw.get("todos") or []) if isinstance(item, dict)],
        "ai_guidance": dict(raw.get("ai_guidance") or {}),
        "meta": dict(raw.get("meta") or {}),
    }


def spec_hash(spec: Dict[str, Any]) -> str:
    """Stable sha256 over canonical JSON (sorted keys, compact separators)."""
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "PLAYBOOK_SCHEMA_VERSION",
    "PlaybookValidationError",
    "is_compatible",
    "normalize_playbook",
    "spec_hash",
]
