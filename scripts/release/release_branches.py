#!/usr/bin/env python
"""Sage Release Branch Lifecycle Manager.

Manages:
  - release/vX.Y.0   (stabilization branch, created from first rc.1 tag)
  - release/stable   (downstream consumption mirror, main line)
  - release/stable-win7  (downstream consumption mirror, win7 LTS line)

Subcommands:
  create         Create release/vX.Y.0 from --tag (idempotent)
  promote-stable Update release/stable[-win7] mirror to --tag (idempotent)
  finalize       Merge release/vX.Y.0 back to main, delete branch

Exit codes (per docs/superpowers/specs/2026-07-10-release-branch-strategy-design.md §3.1):
  0  success / idempotent skip
  1  generic error (git command failed, etc.)
  2  cross-minor guard: previous release/vX.Y.0 not finalized
  3  cherry-pick conflict (during finalize merge to main)
  4  force-with-lease detected remote ref diverged
  5  finalize refused: main is ahead of vX.Y.0
  6  invalid tag format
"""
import argparse
import re
import subprocess
import sys


TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?(-win7)?$")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create release/vX.Y.0 from tag")
    p_create.add_argument("--tier", required=True, choices=["rc"])
    p_create.add_argument("--tag", required=True)
    p_create.add_argument("--version", required=True)

    p_promote = sub.add_parser("promote-stable", help="Update release/stable[-win7] mirror")
    p_promote.add_argument("--tier", required=True, choices=["stable"])
    p_promote.add_argument("--tag", required=True)
    p_promote.add_argument("--branch", default="release/stable")

    p_finalize = sub.add_parser("finalize", help="Merge release/vX.Y.0 back to main and delete")
    p_finalize.add_argument("--version", required=True)
    p_finalize.add_argument("--main-branch", default="main")

    return parser.parse_args()


def validate_tag(tag):
    return bool(TAG_RE.match(tag))


def cmd_create(args):
    """Create release/vX.Y.0 from tag. Idempotent."""
    branch_name = f"release/v{args.version}"
    tag = args.tag

    # git branch <branch> <tag>
    result = subprocess.run(
        ["git", "branch", branch_name, tag],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print(f"created branch {branch_name} at {tag}")
        return 0

    # Idempotent: branch already exists
    if "already exists" in result.stderr:
        print(f"branch {branch_name} already exists, skipping", file=sys.stderr)
        return 0

    # Other git error
    print(f"git branch failed: {result.stderr}", file=sys.stderr)
    return 1


def main():
    args = parse_args()

    if hasattr(args, "tag"):
        if not validate_tag(args.tag):
            print(f"invalid tag format: {args.tag}", file=sys.stderr)
            print("expected: vX.Y.Z[-tier.N[-win7]]", file=sys.stderr)
            return 6

    if args.cmd == "create":
        return cmd_create(args)
    elif args.cmd == "promote-stable":
        print(f"subcommand {args.cmd} not yet implemented (Task 2)", file=sys.stderr)
        return 1
    elif args.cmd == "finalize":
        print(f"subcommand {args.cmd} not yet implemented (Task 2)", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())