"""CLI for validating SKILL.md files.

Use as ``python -m backend.cli.skills lint``; packaged ``sage`` wrappers can
forward the same ``skills lint`` arguments here.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from backend.cli.checks.skills import discover_skill_roots, lint_skill_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sage skills")
    subparsers = parser.add_subparsers(dest="command")
    lint = subparsers.add_parser("lint", help="validate SKILL.md frontmatter")
    lint.add_argument("roots", nargs="*", type=Path, help="skill roots (defaults to discovered roots)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "lint":
        build_parser().print_help()
        return 2
    roots = args.roots if args.roots else discover_skill_roots()
    roots = [root for root in roots if root.is_dir()]
    if not roots:
        sys.stdout.write("未配置技能目录\n")
        return 0
    messages = lint_skill_files(roots)
    if messages:
        sys.stdout.write("\n".join(messages) + "\n")
        return 1
    sys.stdout.write(f"发现 {len(roots)} 个技能根，全部合法\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
