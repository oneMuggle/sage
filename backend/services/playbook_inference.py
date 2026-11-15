"""Deterministic playbook stage inference (2026-11-14).

Infers a project's likely stages from what already exists on disk, so the user
can start from a grounded draft instead of a blank conversation:

1. directory scan — top-level folders named like ``01_开题`` / ``2-实施`` are
   taken as stage order + label, including the documents inside them;
2. git history — commit subjects are bucketed by phase keywords (开题/设计/
   开发/测试/验收/结题...) when the directory scan is inconclusive.

Results are advisory only: the caller shows them to the user, who confirms
before anything is bound to the project.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_DIR_STAGES = 12
MAX_ARTIFACTS_PER_STAGE = 5
GIT_LOG_LIMIT = 200
GIT_TIMEOUT_SECONDS = 5

_SKIP_DIRS = {
    ".git",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

_DOC_SUFFIXES = (".md", ".markdown", ".txt", ".docx", ".doc", ".pdf", ".xlsx", ".pptx")

_NUMBERED_DIR = re.compile(r"^\s*(\d{1,3})\s*[_\-\s.、]*\s*(.+?)\s*$")

_PHASE_KEYWORDS: List[tuple] = [
    ("开题", ("开题", "选题", "立项", "kickoff", "proposal")),
    ("需求", ("需求", "调研", "分析", "requirement")),
    ("设计", ("设计", "方案", "架构", "design")),
    ("实施", ("实施", "开发", "编码", "实现", "develop", "implement")),
    ("测试", ("测试", "验证", "test", "qa")),
    ("验收", ("验收", "评审", "review", "accept")),
    ("结题", ("结题", "归档", "交付", "release", "wrap")),
]

_CONVENTIONAL_SCOPE = re.compile(r"^[a-z]+(?:\(([^)]+)\))?!?:")


@dataclass
class InferredStage:
    label: str
    source: str
    confidence: float
    artifacts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "source": self.source,
            "confidence": self.confidence,
            "artifacts": list(self.artifacts),
        }


@dataclass
class InferenceResult:
    stages: List[InferredStage]
    confidence: float
    source: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stages": [stage.to_dict() for stage in self.stages],
            "confidence": self.confidence,
            "source": self.source,
            "rationale": self.rationale,
        }


def _artifact_labels(directory: str) -> List[str]:
    labels: List[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                if not entry.is_file(follow_symlinks=False):
                    continue
                path = Path(entry.name)
                if path.suffix.lower() not in _DOC_SUFFIXES:
                    continue
                if path.stem:
                    labels.append(path.stem)
                if len(labels) >= MAX_ARTIFACTS_PER_STAGE:
                    break
    except OSError:
        return []
    return labels


def infer_from_directory(project_path: str) -> InferenceResult:
    """Infer stages from numbered top-level directories."""
    if not project_path or not os.path.isdir(project_path):
        return InferenceResult([], 0.0, "directory", "项目目录不存在或不可读")

    numbered: List[tuple] = []
    plain_dirs: List[str] = []
    try:
        with os.scandir(project_path) as entries:
            for entry in entries:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                name = entry.name
                if name.startswith(".") or name in _SKIP_DIRS:
                    continue
                match = _NUMBERED_DIR.match(name)
                if match:
                    numbered.append((int(match.group(1)), match.group(2), entry.path))
                else:
                    plain_dirs.append(entry.path)
    except OSError as exc:
        logger.warning("playbook inference: cannot scan %s: %s", project_path, exc)
        return InferenceResult([], 0.0, "directory", "项目目录扫描失败")

    numbered.sort(key=lambda item: item[0])
    stages: List[InferredStage] = []
    for _order, label, path in numbered[:MAX_DIR_STAGES]:
        stages.append(
            InferredStage(
                label=label,
                source="directory",
                confidence=0.8,
                artifacts=_artifact_labels(path),
            )
        )

    if len(stages) >= 2:
        return InferenceResult(
            stages=stages,
            confidence=0.8,
            source="directory",
            rationale=f"检测到 {len(stages)} 个带序号的阶段目录",
        )

    if stages:
        return InferenceResult(
            stages=stages,
            confidence=0.5,
            source="directory",
            rationale=f"仅检测到 {len(stages)} 个带序号的阶段目录",
        )

    if plain_dirs:
        return InferenceResult(
            stages=[],
            confidence=0.2,
            source="directory",
            rationale=f"目录下 {len(plain_dirs)} 个子目录没有阶段编号，建议补充描述",
        )

    return InferenceResult([], 0.0, "directory", "目录下没有可识别的子目录")


def infer_from_git_history(project_path: str) -> InferenceResult:
    """Infer stages from phase keywords in recent commit subjects."""
    if not project_path or not os.path.isdir(project_path):
        return InferenceResult([], 0.0, "git", "项目目录不存在或不可读")

    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [
                "git",
                "-C",
                project_path,
                "log",
                "--no-merges",
                f"-n{GIT_LOG_LIMIT}",
                "--pretty=%s",
            ],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(
            "playbook inference: git log failed for %s: %s", project_path, exc
        )
        return InferenceResult([], 0.0, "git", "无法读取 git 提交历史")

    if completed.returncode != 0:
        return InferenceResult([], 0.0, "git", "项目不是 git 仓库或没有提交历史")

    subjects = [
        line.strip() for line in (completed.stdout or "").splitlines() if line.strip()
    ]
    if not subjects:
        return InferenceResult([], 0.0, "git", "提交历史为空")

    hits: Dict[str, int] = {}
    first_seen: Dict[str, int] = {}
    for index, subject in enumerate(subjects):
        lowered = subject.lower()
        scope_match = _CONVENTIONAL_SCOPE.match(lowered)
        scope = scope_match.group(1) if scope_match else None
        for label, keywords in _PHASE_KEYWORDS:
            if scope and any(keyword in scope for keyword in keywords):
                hits.setdefault(label, 0)
                first_seen.setdefault(label, index)
            if any(keyword in lowered for keyword in keywords):
                hits[label] = hits.get(label, 0) + 1
                first_seen.setdefault(label, index)

    if not hits:
        return InferenceResult([], 0.0, "git", "提交信息中没有明显的阶段关键词")

    ordered = sorted(hits.items(), key=lambda item: first_seen.get(item[0], 0))
    total_hits = sum(hits.values()) or 1
    stages = [
        InferredStage(
            label=label,
            source="git",
            confidence=round(min(0.75, count / 10.0), 2),
        )
        for label, count in ordered
    ]
    return InferenceResult(
        stages=stages,
        confidence=round(min(0.75, total_hits / 20.0), 2),
        source="git",
        rationale=f"从 {len(subjects)} 条提交信息中识别出阶段关键词",
    )


def infer_project_stages(project: Any) -> InferenceResult:
    """Combine directory and git signals into one advisory result."""
    project_path = str(getattr(project, "path", "") or "")
    directory_result = infer_from_directory(project_path)
    if len(directory_result.stages) >= 2:
        return directory_result

    git_result = infer_from_git_history(project_path)
    if len(git_result.stages) >= 2:
        return git_result

    if directory_result.stages:
        return directory_result
    if git_result.stages:
        return git_result
    return InferenceResult(
        stages=[],
        confidence=0.0,
        source="none",
        rationale=directory_result.rationale
        if directory_result.rationale
        else git_result.rationale,
    )


def inferred_spec(
    project: Any, result: Optional[InferenceResult] = None
) -> Optional[Dict[str, Any]]:
    """Turn an inference result into a minimal playbook-shaped draft."""
    result = result or infer_project_stages(project)
    if not result.stages:
        return None
    stages: List[Dict[str, Any]] = []
    for index, stage in enumerate(result.stages, start=1):
        artifacts = [
            {
                "id": f"artifact-{index}-{artifact_index}",
                "label": label,
                "required": True,
                "match": {"globs": [f"**/{label}*"], "min_count": 1},
            }
            for artifact_index, label in enumerate(stage.artifacts, start=1)
        ]
        stages.append(
            {
                "id": f"stage-{index}",
                "label": stage.label,
                "order": index,
                "objective": "",
                "artifacts": artifacts,
                "exit_criteria": [],
                "rules": [],
                "recommended_milestones": [],
            }
        )
    return {
        "schema_version": "1.0",
        "id": "inferred-{}".format(getattr(project, "id", ""))[:128],
        "name": "{} 规程（推断）".format(getattr(project, "name", "") or "项目"),
        "description": result.rationale,
        "applies_to": {"project_types": [], "sub_types": []},
        "directory_layout": [],
        "stages": stages,
        "global_rules": [],
        "todos": [],
        "ai_guidance": {},
        "meta": {"author": "Sage 推断", "confidence": result.confidence},
    }


__all__ = [
    "InferenceResult",
    "InferredStage",
    "infer_from_directory",
    "infer_from_git_history",
    "infer_project_stages",
    "inferred_spec",
]
