"""Craft rule loader — loads quality-guard rules from content/craft/*.md."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, ConfigDict


class CraftRule(BaseModel):
    """A single craft rule (one markdown file)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    applies_to: str
    priority: int
    content: str


def _parse_craft_md(content: str, fallback_id: str) -> CraftRule:
    """Parse YAML frontmatter from a craft markdown file.

    Tolerant by design: a malformed file never raises — it degrades to
    defaults so one bad rule cannot break every generation.
    """
    match = re.match(
        r"^---[ \t]*\r?\n(.*?)^---[ \t]*\r?\n?(.*)",
        content,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        return CraftRule(
            id=fallback_id,
            name=fallback_id,
            description="",
            applies_to="both",
            priority=99,
            content=content,
        )

    fm: dict = {}
    for line in match.group(1).split("\n"):
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = raw.strip().strip('"').strip("'")
        if key == "priority":
            try:
                fm[key] = int(float(value)) if value else 99
            except (TypeError, ValueError):
                fm[key] = 99
        else:
            fm[key] = value

    body = re.sub(r"^\s*#\s+[^\n]*\n", "", match.group(2), count=1)

    return CraftRule(
        id=fm.get("id", fallback_id),
        name=fm.get("name", fallback_id),
        description=fm.get("description", ""),
        applies_to=fm.get("applies_to", "both"),
        priority=int(fm.get("priority", 99)),
        content=body,
    )


class CraftRuleRegistry:
    """Load and query craft rules from a content directory."""

    def __init__(self, content_dir: Path) -> None:
        self._content_dir = content_dir
        self._craft_dir = content_dir / "craft"
        self._cache: Dict[str, CraftRule] = {}

    def list_rules(self) -> List[CraftRule]:
        """List all available craft rules, sorted by priority.

        Unreadable or malformed files are skipped rather than raising, so a
        single broken rule cannot disable generation for every project.
        """
        if not self._craft_dir.exists():
            return []
        by_id: Dict[str, CraftRule] = {}
        for md_file in sorted(self._craft_dir.glob("*.md")):
            rule_id = md_file.stem
            if rule_id not in self._cache:
                try:
                    text = md_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                self._cache[rule_id] = _parse_craft_md(text, rule_id)
            rule = self._cache[rule_id]
            by_id[rule.id or rule_id] = rule
        return sorted(by_id.values(), key=lambda r: r.priority)

    def rules_for_kind(self, template_kind: str) -> List[CraftRule]:
        """Return rules applicable to a given template kind, sorted by priority."""
        return [
            r
            for r in self.list_rules()
            if r.applies_to in ("both", template_kind)
        ]
