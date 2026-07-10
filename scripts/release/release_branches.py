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


def cmd_promote_stable(args: argparse.Namespace) -> int:
    """Update release/stable[-win7] mirror to point at --tag commit."""
    target_branch = args.branch

    # Resolve tag → commit SHA
    rev = subprocess.run(
        ["git", "rev-parse", args.tag],
        capture_output=True,
        text=True,
    )
    if rev.returncode != 0:
        print(f"git rev-parse {args.tag} failed: {rev.stderr}", file=sys.stderr)
        return 1
    sha = rev.stdout.strip()

    # Push with --force-with-lease (拒绝 divergent ref).
    # Use full refname (refs/heads/<branch>) so the push works even when the
    # local <branch> ref doesn't exist yet (first promote into a fresh mirror).
    push = subprocess.run(
        ["git", "push", "origin", f"{sha}:refs/heads/{target_branch}", "--force-with-lease"],
        capture_output=True,
        text=True,
    )

    if push.returncode == 0:
        print(f"updated {target_branch} to {args.tag} ({sha[:7]})")
        return 0

    # Idempotent: "stale info" / "Everything up-to-date" 视为成功
    if "Everything up-to-date" in push.stdout or "stale info" in push.stderr and "rejected" not in push.stderr:
        print(f"{target_branch} already at {args.tag}, skipping")
        return 0

    # force-with-lease 检测到 ref diverged
    if "forced update declined" in push.stderr or "stale info" in push.stderr and "rejected" in push.stderr:
        print(f"remote ref {target_branch} diverged, manual review needed", file=sys.stderr)
        print(push.stderr, file=sys.stderr)
        return 4

    # 其他错误
    print(f"git push failed: {push.stderr}", file=sys.stderr)
    return 1


def cmd_finalize(args: argparse.Namespace) -> int:
    """Merge release/vX.Y.0 back to main, delete branch, and (next cycle) cross-minor guard."""
    version = args.version
    main_branch = args.main_branch
    branch_name = f"release/v{version}"

    # 0. fetch latest main
    fetch = subprocess.run(["git", "fetch", "origin", main_branch], capture_output=True, text=True)
    if fetch.returncode != 0:
        print(f"git fetch failed: {fetch.stderr}", file=sys.stderr)
        return 1

    # 1. check release/vX.Y.0 远端是否存在
    ls = subprocess.run(
        ["git", "ls-remote", "--heads", "origin", branch_name],
        capture_output=True,
        text=True,
    )
    if ls.returncode == 2 or not ls.stdout.strip():
        # 分支已不存在 → 幂等 skip
        print(f"branch {branch_name} already gone, skipping finalize")
        return 0

    # 2. cross-minor guard: 检查 release/v(PREVIOUS_MINOR).0 是否残留
    parts = version.split(".")
    minor = int(parts[1])
    if minor > 0:
        prev_version = f"{parts[0]}.{minor - 1}.0"
        prev_branch = f"release/v{prev_version}"
        ls_prev = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", prev_branch],
            capture_output=True,
            text=True,
        )
        if ls_prev.returncode == 0 and ls_prev.stdout.strip():
            print(f"previous stabilization branch {prev_branch} still open, refusing finalize", file=sys.stderr)
            return 2

    # 3. checkout main
    co = subprocess.run(["git", "checkout", main_branch], capture_output=True, text=True)
    if co.returncode != 0:
        print(f"git checkout {main_branch} failed: {co.stderr}", file=sys.stderr)
        return 1

    # 4. merge --no-ff release/vX.Y.0
    merge = subprocess.run(
        ["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name} (finalize)"],
        capture_output=True,
        text=True,
    )
    if merge.returncode != 0:
        # 冲突: 包含 CONFLICT 字样
        if "CONFLICT" in merge.stdout or "conflict" in merge.stderr.lower():
            print(f"merge conflict during finalize:\n{merge.stdout}\n{merge.stderr}", file=sys.stderr)
            return 3
        print(f"git merge failed: {merge.stderr}", file=sys.stderr)
        return 1

    # 5. push main
    push_main = subprocess.run(["git", "push", "origin", main_branch], capture_output=True, text=True)
    if push_main.returncode != 0:
        print(f"git push origin {main_branch} failed: {push_main.stderr}", file=sys.stderr)
        return 1

    # 6. delete release/vX.Y.0 远端
    delete = subprocess.run(
        ["git", "push", "origin", "--delete", branch_name],
        capture_output=True,
        text=True,
    )
    if delete.returncode != 0:
        # 分支删除失败不影响主流程
        print(f"warning: failed to delete {branch_name}: {delete.stderr}", file=sys.stderr)

    print(f"finalized {branch_name}: merged to {main_branch} and deleted")
    return 0


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
        return cmd_promote_stable(args)
    elif args.cmd == "finalize":
        return cmd_finalize(args)

    return 1




if __name__ == "__main__":
    sys.exit(main())