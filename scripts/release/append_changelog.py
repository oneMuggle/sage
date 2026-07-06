#!/usr/bin/env python3
"""Sage CHANGELOG section inserter.

Inserts a new tier section (alpha/beta/rc/stable) into CHANGELOG.md
between [Unreleased] and the latest existing version section.

Usage:
    python append_changelog.py \\
        --changelog CHANGELOG.md \\
        --since-tag v0.4.2-lts \\
        --tier alpha \\
        --tag v0.5.0-alpha.1 \\
        --date 2026-07-06 \\
        --milestone "M1" \\
        --known-issues "issue/123"
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def categorize_commits(since_tag: str, cwd: str = ".") -> dict[str, list[str]]:
    """Parse git log since since_tag and categorize by Conventional Commits type."""
    result = subprocess.run(
        ["git", "log", f"{since_tag}..HEAD", "--pretty=%s"],
        capture_output=True, text=True, check=True, cwd=cwd,
    )
    subjects = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    categorized: dict[str, list[str]] = {
        "feat": [], "fix": [], "refactor": [], "perf": [],
        "docs": [], "test": [], "chore": [], "ci": [], "build": [],
        "style": [],
    }
    pattern = re.compile(r"^(?P<type>[a-z]+)(?:\(.+?\))?!?:\s*(?P<subject>.+)$")
    for s in subjects:
        m = pattern.match(s)
        if m:
            t = m.group("type")
            if t in categorized:
                categorized[t].append(s)
                continue
        categorized.setdefault("other", []).append(s)
    return categorized


def render_section(
    tier: str,
    tag: str,
    date: str,
    categorized: dict[str, list[str]],
    milestone: str,
    known_issues: str,
) -> str:
    """Render the markdown section content (without the header line)."""
    sections = []
    if categorized["feat"]:
        sections.append("### Added\n" + "\n".join(f"- {c}" for c in categorized["feat"]))
    if categorized["fix"]:
        sections.append("### Fixed\n" + "\n".join(f"- {c}" for c in categorized["fix"]))
    if categorized["refactor"] or categorized["perf"]:
        refactor_lines = categorized["refactor"] + categorized["perf"]
        sections.append("### Changed\n" + "\n".join(f"- {c}" for c in refactor_lines))
    if not sections:
        sections.append("### Changed\n- (no categorized commits)")
    body = "\n\n".join(sections)

    if tier in ("alpha", "beta", "rc") and known_issues:
        issues = [i.strip() for i in known_issues.split(",") if i.strip()]
        body += "\n\n### Known Issues\n" + "\n".join(f"- {i}" for i in issues)

    if milestone:
        milestones = [m.strip() for m in milestone.split(",") if m.strip()]
        body += f"\n\n🔗 Milestone(s): {', '.join(milestones)}"

    return body


def insert_section(
    changelog_path: Path,
    tier: str,
    tag: str,
    date: str,
    section_body: str,
) -> None:
    """Insert new section into CHANGELOG.md after [Unreleased] block."""
    content = changelog_path.read_text(encoding="utf-8")
    new_header = f"## [{tag}] - {date}"
    new_section = f"\n## {new_header}\n\n{section_body}\n"

    lines = content.split("\n")
    insert_idx = None
    in_unreleased = False
    for i, line in enumerate(lines):
        if line.startswith("## [Unreleased]"):
            in_unreleased = True
            continue
        if in_unreleased and line.startswith("## [v"):
            insert_idx = i
            break
    if insert_idx is None:
        lines.append(new_section)
    else:
        lines.insert(insert_idx, new_section.rstrip("\n"))
        lines.insert(insert_idx + 1, "")

    changelog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changelog", required=True, help="Path to CHANGELOG.md")
    parser.add_argument("--since-tag", required=True, help="Tag to diff from")
    parser.add_argument("--tier", required=True, choices=["alpha", "beta", "rc", "stable"])
    parser.add_argument("--tag", required=True, help="New tag (e.g. v0.5.0-beta.1)")
    parser.add_argument("--date", required=True, help="Release date (YYYY-MM-DD)")
    parser.add_argument("--milestone", default="", help="Comma-separated milestone names")
    parser.add_argument("--known-issues", default="", help="Comma-separated known issue refs")
    parser.add_argument("--cwd", default=".", help="Git repo cwd")
    args = parser.parse_args()

    categorized = categorize_commits(args.since_tag, cwd=args.cwd)
    section_body = render_section(
        tier=args.tier,
        tag=args.tag,
        date=args.date,
        categorized=categorized,
        milestone=args.milestone,
        known_issues=args.known_issues,
    )
    insert_section(
        changelog_path=Path(args.changelog),
        tier=args.tier,
        tag=args.tag,
        date=args.date,
        section_body=section_body,
    )
    print(f"Inserted {args.tag} into {args.changelog}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
