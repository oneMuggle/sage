"""Deterministic playbook auditor: artifact matching, completeness, stage hints.

No LLM is required. The auditor scans the project directory (excluding VCS,
dependency and cache directories), matches each artifact's globs, evaluates
existence/size/freshness, and produces a per-stage checklist plus a suggested
stage with evidence. Stage changes always require explicit user confirmation.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".sage",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}
SENSITIVE_NAMES = {".env", "credentials.json", "id_rsa", "id_ed25519"}
TEXT_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".tex",
    ".bib",
}
MAX_TEXT_BYTES = 200_000
MAX_EVIDENCE_MATCHES = 5


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a playbook glob to regex.

    Supports ``*`` (no path separator), ``?``, ``**`` (any depth, including
    zero directories when followed by ``/``) and ``{a,b}`` alternatives.
    """
    pattern = pattern.replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    out: List[str] = ["^"]
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            if index + 1 < length and pattern[index + 1] == "*":
                index += 2
                if index < length and pattern[index] == "/":
                    out.append("(?:.*/)?")
                    index += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                index += 1
        elif char == "?":
            out.append("[^/]")
            index += 1
        elif char == "{":
            end = pattern.find("}", index + 1)
            if end == -1:
                out.append(re.escape(char))
                index += 1
            else:
                options = pattern[index + 1 : end].split(",")
                out.append("(?:" + "|".join(re.escape(option) for option in options) + ")")
                index = end + 1
        else:
            out.append(re.escape(char))
            index += 1
    out.append("$")
    return re.compile("".join(out))


def _iter_files(root: Path) -> Iterable[Path]:
    root = root.resolve()
    for current_dir, dirnames, filenames in os.walk(str(root), followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
        for filename in filenames:
            if filename in SENSITIVE_NAMES or filename.startswith(".env"):
                continue
            path = Path(current_dir) / filename
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved != root and root not in resolved.parents:
                continue
            yield path


class ProjectFileIndex:
    """One-pass project file index shared by all artifact globs in an audit."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.entries: List[tuple] = []
        if self.root.is_dir():
            for path in _iter_files(self.root):
                try:
                    relative = path.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                self.entries.append((path, relative))

    def match(self, pattern: str) -> List[Path]:
        regex = _glob_to_regex(pattern)
        return [path for path, relative in self.entries if regex.match(relative)]


def match_glob(root: Path, pattern: str) -> List[Path]:
    """Return files under ``root`` matching a playbook glob, sorted by path."""
    matches = ProjectFileIndex(root).match(pattern)
    matches.sort(key=lambda item: item.as_posix())
    return matches


def _read_text_head(path: Path) -> str:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return ""
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_TEXT_BYTES)
        return data.decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _check_content(paths: List[Path], checks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    text = ""
    for path in paths[:MAX_EVIDENCE_MATCHES]:
        if path.suffix.lower() in TEXT_SUFFIXES:
            text += _read_text_head(path)
            if len(text) >= MAX_TEXT_BYTES:
                break
    for check in checks:
        check_type = check.get("type")
        keywords = [str(item) for item in (check.get("keywords") or []) if str(item)]
        if check_type in {"keyword", "keyword_or_llm"} and keywords:
            hits = [keyword for keyword in keywords if keyword in text]
            status = "pass" if hits else ("fail" if text else "pending")
            results.append(
                {
                    "id": check.get("id"),
                    "label": check.get("label"),
                    "type": check_type,
                    "status": status,
                    "keywords": keywords,
                    "hits": hits,
                    "llm_prompt": check.get("llm_prompt") or "",
                }
            )
        else:
            results.append(
                {
                    "id": check.get("id"),
                    "label": check.get("label"),
                    "type": check_type,
                    "status": "pending",
                    "keywords": keywords,
                    "hits": [],
                    "llm_prompt": check.get("llm_prompt") or "",
                }
            )
    return results


def _condition_true(expr: Any, project: Any, state: Dict[str, Any]) -> bool:
    """Evaluate a small, safe subset of ``required_when`` expressions.

    Supported forms:
    - ``project.<field>`` (boolean truthiness; ``contains_human_subjects``
      reads from ``state.conditions``)
    - ``state.<key>`` (boolean truthiness)
    - ``project.<field> == value`` / ``state.<key> == value``

    Unknown expressions evaluate to False, so an unrecognized condition is
    treated as "not required" rather than causing false missing reports.
    """
    text = str(expr or "").strip()
    if not text:
        return True
    conditions = state.get("conditions") if isinstance(state.get("conditions"), dict) else {}
    if "==" in text:
        left, right = text.split("==", 1)
        left = left.strip()
        right = right.strip().strip("'\"")
        if left.startswith("project."):
            result = str(getattr(project, left[len("project.") :], "") or "") == right
        elif left.startswith("state."):
            result = str(conditions.get(left[len("state.") :], "") or "") == right
        else:
            result = False
    elif text.startswith("state."):
        result = bool(conditions.get(text[len("state.") :]))
    elif text.startswith("project."):
        field = text[len("project.") :]
        if field == "contains_human_subjects":
            result = bool(conditions.get(field))
        elif field == "has_git":
            result = str(getattr(project, "vcs_mode", "") or "") == "git"
        else:
            result = bool(getattr(project, field, False))
    else:
        result = False
    return result


def _effective_required(project: Any, artifact: Dict[str, Any], state: Dict[str, Any]) -> bool:
    if not _condition_true(artifact.get("required_when"), project, state):
        return False
    return bool(artifact.get("required", True))


def _artifact_audit(
    index: ProjectFileIndex,
    project: Any,
    stage_id: str,
    artifact: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    root = index.root
    waivers: Set[str] = {str(item) for item in (state.get("waivers") or [])}
    artifact_key = "{}.{}".format(stage_id, artifact["id"])
    required = _effective_required(project, artifact, state)
    match = artifact.get("match") or {}
    min_bytes = int(match.get("min_bytes") or 0)
    min_count = max(1, int(match.get("min_count") or 1))

    matches: List[Path] = []
    for pattern in match.get("globs") or []:
        for path in index.match(pattern):
            if path not in matches:
                matches.append(path)
    matches.sort(key=lambda item: item.as_posix())

    valid: List[Path] = []
    for path in matches:
        try:
            if path.stat().st_size >= min_bytes:
                valid.append(path)
        except OSError:
            continue

    latest_mtime: Optional[float] = None
    for path in valid:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime

    status = "present"
    if artifact_key in waivers:
        status = "waived"
    elif len(valid) < min_count:
        status = "optional" if not required else "missing"
    else:
        max_age_days = match.get("max_age_days")
        if (
            max_age_days
            and latest_mtime is not None
            and (time.time() - latest_mtime) > int(max_age_days) * 86400
        ):
            status = "stale"

    relative_matches = []
    for path in valid[:MAX_EVIDENCE_MATCHES]:
        try:
            relative_matches.append(path.relative_to(root.resolve()).as_posix())
        except ValueError:
            continue

    target_dir = artifact.get("target_dir")
    misplaced: List[str] = []
    if target_dir:
        for path in valid[:20]:
            try:
                relative = path.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if relative != target_dir and not relative.startswith(target_dir + "/"):
                misplaced.append(relative)

    return {
        "id": artifact["id"],
        "label": artifact.get("label", artifact["id"]),
        "required": required,
        "required_when": artifact.get("required_when"),
        "status": status,
        "target_dir": target_dir,
        "evidence": {
            "matches": relative_matches,
            "misplaced": misplaced[:10],
            "count": len(valid),
            "latest_mtime": int(latest_mtime) if latest_mtime is not None else None,
            "globs": list(match.get("globs") or []),
        },
        "checks": _check_content(valid, artifact.get("content_checks") or []),
        "missing_action": artifact.get("missing_action"),
    }


def _criterion_status(
    criterion: Dict[str, Any],
    artifacts_by_id: Dict[str, Dict[str, Any]],
    stage_id: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    criterion_type = criterion.get("type")
    status = "pending"
    if criterion_type == "artifact":
        artifact = artifacts_by_id.get(str(criterion.get("artifact_id") or ""))
        if artifact is not None and artifact["status"] in {"present", "stale", "waived"}:
            status = "done"
    elif criterion_type == "manual":
        manual_done = {str(item) for item in (state.get("manual_done") or [])}
        if "{}.{}".format(stage_id, criterion.get("id")) in manual_done:
            status = "done"
    return {
        "id": criterion.get("id"),
        "label": criterion.get("label") or criterion.get("id"),
        "type": criterion_type,
        "status": status,
    }


def _detect_stage(stages: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not stages:
        return {"id": None, "confidence": 0.0, "evidence": []}
    completed = [stage for stage in stages if stage["progress"] >= 70]
    if completed:
        candidate = completed[-1]
        position = stages.index(candidate)
        next_stage = stages[position + 1] if position + 1 < len(stages) else None
        confidence = 0.9 if next_stage is None else 0.75
        evidence = ["stage:%s progress=%d%%" % (candidate["id"], candidate["progress"])]
        if next_stage is not None:
            evidence.append("next:%s progress=%d%%" % (next_stage["id"], next_stage["progress"]))
        return {"id": candidate["id"], "confidence": confidence, "evidence": evidence}

    started = [stage for stage in stages if stage["progress"] > 0]
    candidate = started[0] if started else stages[0]
    evidence = ["stage:%s progress=%d%%" % (candidate["id"], candidate["progress"])]
    return {"id": candidate["id"], "confidence": 0.5 if started else 0.3, "evidence": evidence}


def audit_playbook(
    project: Any,
    spec: Dict[str, Any],
    *,
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Audit a project against a playbook spec.

    Args:
        project: object or dict with at least ``path``.
        spec: normalized playbook spec.
        state: project playbook state (waivers, manual_done, current_stage).

    Returns:
        A JSON-serializable audit report. Never raises for missing files.
    """
    root = Path(getattr(project, "path", None) or project["path"]).expanduser()
    index = ProjectFileIndex(root)
    state = state or {}
    stages_out: List[Dict[str, Any]] = []
    total_required = 0
    total_done = 0

    for stage in spec.get("stages") or []:
        artifacts = [
            _artifact_audit(index, project, stage["id"], artifact, state)
            for artifact in stage.get("artifacts") or []
        ]
        by_id = {artifact["id"]: artifact for artifact in artifacts}
        required = [artifact for artifact in artifacts if artifact["required"]]
        done = [
            artifact
            for artifact in required
            if artifact["status"] in {"present", "stale", "waived"}
        ]
        progress = 100 if not required else int(round(100.0 * len(done) / len(required)))
        entries = [
            _criterion_status(criterion, by_id, stage["id"], state)
            for criterion in stage.get("exit_criteria") or []
        ]
        total_required += len(required)
        total_done += len(done)
        stages_out.append(
            {
                "id": stage["id"],
                "label": stage.get("label", stage["id"]),
                "order": stage.get("order", 0),
                "objective": stage.get("objective", ""),
                "progress": progress,
                "required_total": len(required),
                "required_done": len(done),
                "remaining": [
                    {"id": item["id"], "label": item["label"], "missing_action": item.get("missing_action")}
                    for item in required
                    if item["status"] == "missing"
                ],
                "artifacts": artifacts,
                "exit_criteria": entries,
            }
        )

    overall_progress = 100 if total_required == 0 else int(round(100.0 * total_done / total_required))
    stages_out.sort(key=lambda item: item["order"])
    detected = _detect_stage(stages_out)
    stage_ids = [stage["id"] for stage in stages_out]
    current_stage = state.get("current_stage")
    if current_stage not in stage_ids:
        current_stage = stage_ids[0] if stage_ids else None

    classification_suggestions = []
    seen_moves = set()
    for stage in stages_out:
        for artifact in stage["artifacts"]:
            target_dir = artifact.get("target_dir")
            for relative in artifact["evidence"].get("misplaced") or []:
                move_to = target_dir + "/" + Path(relative).name
                key = (relative, move_to)
                if key in seen_moves:
                    continue
                seen_moves.add(key)
                classification_suggestions.append(
                    {
                        "from": relative,
                        "to": move_to,
                        "artifact_id": artifact["id"],
                        "label": artifact["label"],
                        "stage_id": stage["id"],
                        "reason": f"{artifact['label']} 应位于 {target_dir}/",
                    }
                )

    return {
        "playbook": {"id": spec.get("id"), "name": spec.get("name")},
        "current_stage": current_stage,
        "detected_stage": detected,
        "stages": stages_out,
        "classification_suggestions": classification_suggestions,
        "overall": {
            "required_total": total_required,
            "required_done": total_done,
            "progress": overall_progress,
        },
        "scanned_at": int(time.time() * 1000),
    }


__all__ = ["EXCLUDED_DIRS", "audit_playbook", "match_glob"]
