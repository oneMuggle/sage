"""Lightweight SKILL.md discovery and validation for ``sage doctor``.

This module intentionally uses only the Python standard library. In
particular, it must not import ``backend.skills``.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

from backend.cli.doctor import CheckResult, Severity, register

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FENCE = "---"


class SkillFile(NamedTuple):
    path: Path
    root: Path
    directory_name: str


def discover_skill_roots() -> List[Path]:
    """Return existing skill roots in loader-compatible priority order."""
    roots: List[Path] = []
    configured = os.environ.get("SAGE_SKILLS_DIR", "").strip()
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend((Path.cwd() / "skills", Path.home() / ".sage" / "skills"))
    for candidate in candidates:
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return roots


def _unquote(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("empty value")
    if value[0] in ("'", '"'):
        quote = value[0]
        if len(value) < 2 or value[-1] != quote:
            raise ValueError("unterminated quoted value")
        value = value[1:-1]
        if quote == '"':
            value = value.replace('\\"', '"').replace("\\n", "\n")
    elif value.startswith(("[", "{", "|", ">")):
        raise ValueError("unsupported YAML value")
    return value


def parse_skill_frontmatter(text: str) -> Dict[str, str]:
    """Extract and validate the required scalar fields from SKILL.md."""
    if text.startswith("﻿"):
        text = text[1:]
    if not text.startswith(_FENCE + "\n") and not text.startswith(_FENCE + "\r\n"):
        raise ValueError("missing opening frontmatter fence")
    lines = text.splitlines()
    closing = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == _FENCE), None)
    if closing is None:
        raise ValueError("missing closing frontmatter fence")
    values: Dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing], 2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line or line[:1].isspace():
            raise ValueError(f"invalid frontmatter line {line_number}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z0-9_-]+$", key):
            raise ValueError(f"invalid frontmatter key on line {line_number}")
        if key in values:
            raise ValueError(f"duplicate frontmatter key: {key}")
        try:
            values[key] = _unquote(raw_value)
        except ValueError as exc:
            raise ValueError(f"invalid value for {key}: {exc}")
    for required in ("name", "description"):
        if not values.get(required, "").strip():
            raise ValueError(f"missing or empty frontmatter field: {required}")
    if not _NAME_RE.match(values["name"]) or len(values["name"]) > 64:
        raise ValueError("invalid skill name: {}".format(values["name"]))
    return values


def discover_skill_files(roots: Sequence[Path]) -> List[SkillFile]:
    """Find root-level or immediate child ``SKILL.md`` files."""
    files: List[SkillFile] = []
    for root in roots:
        try:
            root_skill = root / "SKILL.md"
            if root_skill.is_file():
                files.append(SkillFile(root_skill, root, ""))
            children = sorted(root.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                skill_file = child / "SKILL.md"
                if skill_file.is_file():
                    files.append(SkillFile(skill_file, root, child.name))
    return files


def lint_skill_files(roots: Optional[Sequence[Path]] = None) -> List[str]:
    """Return human-readable warnings for discovered skills."""
    selected_roots = list(discover_skill_roots() if roots is None else roots)
    messages: List[str] = []
    names: Dict[str, SkillFile] = {}
    for item in discover_skill_files(selected_roots):
        try:
            metadata = parse_skill_frontmatter(item.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            messages.append(f"{item.path}: {exc}")
            continue
        name = metadata["name"]
        if item.directory_name and name != item.directory_name:
            messages.append(f"{item.path}: name '{name}' does not match parent directory '{item.directory_name}'")
        previous = names.get(name)
        if previous is not None:
            messages.append(f"{item.path}: duplicate skill '{name}'; winner is {previous.path}")
        else:
            names[name] = item
    return messages


@register
class SkillsCheck:
    name = "skills"
    description = "SKILL.md 技能目录与 frontmatter 校验"

    def run(self) -> CheckResult:
        roots = discover_skill_roots()
        if not roots:
            return CheckResult(self.name, Severity.INFO, "未配置技能目录")
        messages = lint_skill_files(roots)
        if messages:
            return CheckResult(self.name, Severity.WARN, "；".join(messages), "运行 sage skills lint 修复 SKILL.md")
        return CheckResult(self.name, Severity.INFO, f"发现 {len(roots)} 个技能根，全部合法")
