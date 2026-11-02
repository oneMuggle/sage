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
MAX_UNCLASSIFIED_FILES = 30
UNCLASSIFIED_MIN_SCORE = 3
DOC_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".doc",
    ".docx",
    ".pdf",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".csv",
    ".tex",
    ".bib",
}
ROOT_IGNORED_NAMES = {
    "readme.md",
    "license",
    "license.md",
    "changelog.md",
    "contributing.md",
    "agents.md",
    "claude.md",
}


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


def _normalize_relative(path: Any) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _split_keywords(text: str) -> List[str]:
    tokens: List[str] = []
    for raw in re.split(r"[、，,;；/\s]+", text or ""):
        token = raw.strip().lower()
        if len(token) >= 2 and not token.isdigit():
            tokens.append(token)
    return tokens


def _dir_name_keyword(path: str) -> str:
    name = _normalize_relative(path).rsplit("/", 1)[-1]
    name = re.sub(r"^[0-9]+[_\-\s.]*", "", name)
    return name.strip().lower()


def _glob_suffix_info(pattern: str) -> tuple:
    """Return ``(suffixes, accepts_any_document)`` for an artifact glob."""
    text = _normalize_relative(pattern)
    if text.endswith("/**/*") or text == "**/*":
        return set(), True
    name = text.rsplit("/", 1)[-1]
    if "." not in name:
        return set(), False
    extension = name.rsplit(".", 1)[1]
    if extension.startswith("{") and extension.endswith("}"):
        values = [item.strip().lower() for item in extension[1:-1].split(",")]
        return {"." + item for item in values if item and not any(ch in item for ch in "*?")}, False
    if any(ch in extension for ch in "*?{}"):
        return set(), False
    return {"." + extension.lower()}, False


def _classification_directories(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}

    def ensure(path: Any) -> Optional[Dict[str, Any]]:
        normalized = _normalize_relative(path)
        if not normalized:
            return None
        return candidates.setdefault(
            normalized, {"keywords": set(), "extensions": set(), "generic": False}
        )

    for entry in spec.get("directory_layout") or []:
        candidate = ensure(entry.get("path"))
        if candidate is None:
            continue
        candidate["keywords"].update(_split_keywords(str(entry.get("purpose") or "")))
        basename = _dir_name_keyword(entry.get("path"))
        if basename:
            candidate["keywords"].add(basename)

    for stage in spec.get("stages") or []:
        for artifact in stage.get("artifacts") or []:
            candidate = ensure(artifact.get("target_dir"))
            if candidate is None:
                continue
            label = str(artifact.get("label") or "").strip().lower()
            if len(label) >= 2:
                candidate["keywords"].add(label)
            for pattern in (artifact.get("match") or {}).get("globs") or []:
                suffixes, generic = _glob_suffix_info(str(pattern))
                candidate["extensions"].update(suffixes)
                candidate["generic"] = candidate["generic"] or generic
    return candidates


def _under_directories(relative: str, directories: Iterable[str]) -> bool:
    return any(
        relative == directory or relative.startswith(directory + "/")
        for directory in directories
    )


def _suggest_destination(
    path: Path,
    relative: str,
    files: Set[str],
    candidates: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    stem = path.stem.lower()
    suffix = path.suffix.lower()
    best_score = 0
    best: Optional[Dict[str, Any]] = None
    for directory, candidate in candidates.items():
        if _under_directories(relative, [directory]):
            continue
        score = 0
        reasons: List[str] = []
        hits = [keyword for keyword in candidate["keywords"] if keyword and keyword in stem]
        if hits:
            score += 3 + min(2, len(hits) - 1)
            reasons.append(f"文件名包含「{hits[0]}」")
        if suffix in candidate["extensions"]:
            score += 2
            reasons.append(f"扩展名 {suffix} 与目标目录产物格式一致")
        elif candidate["generic"] and suffix in DOC_SUFFIXES:
            score += 1
            reasons.append("目标目录收纳该类型文档")
        if score <= best_score or score < UNCLASSIFIED_MIN_SCORE:
            continue
        best_score = score
        best = {"directory": directory, "score": score, "reason": "；".join(reasons[:2])}
    if best is None:
        return None
    destination = "{}/{}".format(best["directory"], path.name)
    if destination in files:
        return None
    return {
        "suggested_to": destination,
        "confidence": round(min(0.95, 0.35 + 0.12 * best_score), 2),
        "reason": best["reason"],
    }


def _unclassified_files(
    index: ProjectFileIndex,
    spec: Dict[str, Any],
    matched: Set[str],
) -> List[Dict[str, Any]]:
    """Suggest a home for document files outside every declared location."""
    candidates = _classification_directories(spec)
    if not candidates:
        return []
    files = {relative for _path, relative in index.entries}
    results: List[Dict[str, Any]] = []
    for path, relative in sorted(index.entries, key=lambda item: item[1]):
        if relative in matched:
            continue
        if _under_directories(relative, candidates.keys()):
            continue
        if path.suffix.lower() not in DOC_SUFFIXES:
            continue
        if path.name.lower() in ROOT_IGNORED_NAMES:
            continue
        suggestion = _suggest_destination(path, relative, files, candidates)
        if suggestion is None:
            continue
        results.append({"path": relative, **suggestion})
        if len(results) >= MAX_UNCLASSIFIED_FILES:
            break
    return results


def _undo_available(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    batch = state.get("last_move_batch")
    if not isinstance(batch, dict):
        return None
    moves = batch.get("moves")
    if not isinstance(moves, list) or not moves:
        return None
    return {"at": int(batch.get("at") or 0), "count": len(moves)}



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

    matched_files: Set[str] = set()
    for stage in spec.get("stages") or []:
        for artifact in stage.get("artifacts") or []:
            for pattern in (artifact.get("match") or {}).get("globs") or []:
                for path in index.match(str(pattern)):
                    try:
                        matched_files.add(path.relative_to(index.root).as_posix())
                    except ValueError:
                        continue

    return {
        "playbook": {"id": spec.get("id"), "name": spec.get("name")},
        "current_stage": current_stage,
        "detected_stage": detected,
        "stages": stages_out,
        "classification_suggestions": classification_suggestions,
        "unclassified_files": _unclassified_files(index, spec, matched_files),
        "undo_available": _undo_available(state),
        "overall": {
            "required_total": total_required,
            "required_done": total_done,
            "progress": overall_progress,
        },
        "scanned_at": int(time.time() * 1000),
    }


__all__ = ["EXCLUDED_DIRS", "audit_playbook", "match_glob"]
