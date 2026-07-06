#!/usr/bin/env python3
"""Sage release tier inference CLI.

Reads git log between two tags, classifies commits by Conventional Commits
prefix, and recommends the next tier (alpha / beta / rc / stable) along with
the specific tag (e.g. v0.5.0-beta.2).

Usage:
    python infer_tier.py \\
        --since-tag v0.4.0 \\
        --target-minor 0.5.0 \\
        --milestone-closed "M1,M2" \\
        --open-blockers 0 \\
        [--bump {minor,patch}] \\
        [--dry-run]

Output: JSON to stdout

Bump semantics:
    --bump minor (default): emit v0.5.0-{alpha,beta,rc}.N or v0.5.0 stable
    --bump patch:           emit v0.5.1 (hotfix; spec §2.2 PATCH 路径)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class TierRecommendation:
    recommended_tier: str
    recommended_tag: str
    confidence: str
    reasons: list[str] = field(default_factory=list)
    next_action: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2)


def run_git_log(since_tag: str, cwd: str = ".") -> list[str]:
    """Return list of commit subject lines since since_tag (exclusive)."""
    result = subprocess.run(
        ["git", "log", f"{since_tag}..HEAD", "--pretty=%s"],
        capture_output=True, text=True, check=True, cwd=cwd,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def count_feat_commits(subjects: list[str]) -> int:
    """Count commits whose subject starts with feat: or feat(scope):"""
    return sum(1 for s in subjects if re.match(r"^feat(\(.+\))?!?:", s))


def has_breaking_change(subjects: list[str]) -> bool:
    """Detect BREAKING CHANGE: in commit body (we use subject here for simplicity).

    For full body parsing, swap to: git log <range> --pretty=%B | grep BREAKING
    """
    return any("BREAKING CHANGE" in s for s in subjects)


def get_current_tier_counters(target_minor: str, cwd: str = ".") -> dict[str, int]:
    """Return counters per tier for the current MINOR from existing tags.

    Example output: {"alpha": 2, "beta": 1, "rc": 0}
    """
    result = subprocess.run(
        ["git", "tag", "--list", f"v{target_minor}-*"],
        capture_output=True, text=True, check=True, cwd=cwd,
    )
    counters: dict[str, int] = {"alpha": 0, "beta": 0, "rc": 0}
    pattern = re.compile(rf"^v{re.escape(target_minor)}-(alpha|beta|rc)\.(\d+)$")
    for tag in result.stdout.splitlines():
        tag = tag.strip()
        if not tag:
            continue
        m = pattern.match(tag)
        if m:
            tier, num = m.group(1), int(m.group(2))
            counters[tier] = max(counters[tier], num)
    return counters


def infer_tier(
    since_tag: str,
    target_minor: str,
    milestone_closed: list[str],
    open_blockers: int,
    bump: str = "minor",
    cwd: str = ".",
) -> TierRecommendation:
    """Main inference logic. Returns TierRecommendation dataclass.

    Args:
        bump: "minor" (default) → tier-based tag (v0.5.0-rc.1 etc.)
              "patch"           → stable hotfix (v0.5.1; spec §2.2 PATCH 路径)
    """
    # PATCH path — spec §2.2: hotfix stable bumps PATCH, no tier logic.
    if bump == "patch":
        # Derive next PATCH from since-tag (e.g. v0.5.0 → v0.5.1).
        m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", since_tag.strip())
        if not m:
            return TierRecommendation(
                recommended_tier="stable",
                recommended_tag="",
                confidence="low",
                reasons=[
                    f"--bump=patch 需要 since_tag 形如 vX.Y.Z (stable); 实际: {since_tag}",
                ],
                next_action="fix --since-tag 指向 stable tag 后重跑",
            )
        major, minor, patch_n = int(m.group(1)), int(m.group(2)), int(m.group(3))
        recommended_tag = f"v{major}.{minor}.{patch_n + 1}"
        return TierRecommendation(
            recommended_tier="stable",
            recommended_tag=recommended_tag,
            confidence="high",
            reasons=[
                f"--bump=patch: {since_tag} → {recommended_tag} (spec §2.2 hotfix)",
            ],
            next_action=f"git tag {recommended_tag} -m 'hotfix' && git push origin {recommended_tag}",
        )

    subjects = run_git_log(since_tag, cwd=cwd)
    feat_count = count_feat_commits(subjects)
    breaking = has_breaking_change(subjects)
    counters = get_current_tier_counters(target_minor, cwd=cwd)

    reasons: list[str] = []

    # Determine tier
    if feat_count == 0:
        tier = "alpha"
        reasons.append(f"累计 feat: {feat_count} 个 (== 0 触发 alpha)")
    elif feat_count < 3 and len(milestone_closed) < 1:
        tier = "alpha"
        reasons.append(f"累计 feat: {feat_count} 个 (< 3 保持 alpha)")
    elif feat_count < 6 and len(milestone_closed) < 2:
        tier = "beta"
        reasons.append(f"累计 feat: {feat_count} 个 (>= 3 触发 beta)")
        reasons.append(f"milestone 闭合: {len(milestone_closed)} 个 (>= 1)")
    elif feat_count >= 6 and len(milestone_closed) >= 2 and open_blockers == 0:
        tier = "rc"
        reasons.append(f"累计 feat: {feat_count} 个 (>= 6) + milestones {len(milestone_closed)} 个 (>= 2) → rc 待签发")
    elif open_blockers > 0:
        tier = "rc"
        reasons.append(f"open blockers: {open_blockers} (> 0 不能 stable)")
    else:
        tier = "stable"
        reasons.append(f"milestone 闭合: {len(milestone_closed)} 个")
        reasons.append(f"open blockers: {open_blockers} (== 0 满足 stable)")

    reasons.append(f"上次 tag {since_tag} 以来 feat 累计 {feat_count} 个")

    if breaking:
        reasons.append("⚠️ 检测到 BREAKING CHANGE，建议 MAJOR+1")

    # Counter
    counter = counters.get(tier, 0) + 1
    if tier == "stable":
        recommended_tag = f"v{target_minor}"
    else:
        recommended_tag = f"v{target_minor}-{tier}.{counter}"

    # Confidence — spec §7.6 ambiguous recommendations emit "low".
    # Three tiers: high (default) / medium (info-light) / low (ambiguous).
    ambiguous = (
        feat_count >= 6
        and open_blockers > 0
        and len(milestone_closed) < 2
    )
    if ambiguous:
        confidence = "low"
        reasons.append(
            "⚠️ 矛盾信号: feat 足够多 (>={}) 但同时有 open blockers ({}) 且 milestones 不足 (<2) — 需人工裁决".format(
                6, open_blockers
            )
        )
    elif tier == "alpha" and feat_count == 0:
        confidence = "medium"
    else:
        confidence = "high"

    return TierRecommendation(
        recommended_tier=tier,
        recommended_tag=recommended_tag,
        confidence=confidence,
        reasons=reasons,
        next_action=f"git tag {recommended_tag} -m '...' && git push origin {recommended_tag}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since-tag", required=True, help="Last released tag (e.g. v0.4.0)")
    parser.add_argument("--target-minor", required=True, help="Target MINOR version (e.g. 0.5.0)")
    parser.add_argument("--milestone-closed", default="", help="Comma-separated closed milestone names (e.g. M1,M2)")
    parser.add_argument("--open-blockers", type=int, default=0, help="Number of open release-blocker issues")
    parser.add_argument(
        "--bump",
        choices=("minor", "patch"),
        default="minor",
        help="Bump type: 'minor' (default; tier-based v0.5.0-rc.1) or 'patch' (stable hotfix v0.5.1; spec §2.2)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Recommend only; do not modify anything")
    args = parser.parse_args()

    milestones = [m.strip() for m in args.milestone_closed.split(",") if m.strip()]

    rec = infer_tier(
        since_tag=args.since_tag,
        target_minor=args.target_minor,
        milestone_closed=milestones,
        open_blockers=args.open_blockers,
        bump=args.bump,
        cwd=".",
    )

    print(rec.to_json())

    if not args.dry_run:
        # Future: maybe write to a file? For now, dry-run IS the mode.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())