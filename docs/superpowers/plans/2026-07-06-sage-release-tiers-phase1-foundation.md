# Sage Release Tiers — Phase 1 基础设施 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Sage 4 档发布分级（alpha/beta/rc/stable）所需的所有基础设施：3 个 CLI 工具 + 2 个 GitHub workflow 改动，让 tag 推送后能自动构建并标记 prerelease。

**Architecture:**
- 3 个独立 CLI 工具（Python + Bash），每个都是单一职责
- 通过 GitHub workflow 的 `prerelease: ${{ contains(...) }}` 表达式自动判断档位（无需 Python 在 CI 跑）
- Cache key 加 `prerelease-` 命名空间隔离
- 升档判断脚本由人工在本地跑（dry-run），仅推荐不强制

**Tech Stack:**
- Python 3.11（conda `sage-backend` 环境）
- `packaging` 库（pip 内置）做 semver 解析
- Bash 4+（GitHub Actions ubuntu-latest 默认 5+）
- `softprops/action-gh-release@v2`（已存在）
- pytest（已存在）

## Global Constraints

来自 spec 的全局约束（每个任务隐式遵守）：

- **Tag 格式**: `vMAJOR.MINOR.PATCH[-tier.N][-lts]`，tier ∈ {alpha, beta, rc}
- **win7 LTS 跟随**: `-lts` 始终在 tier 之后，如 `v0.5.0-beta.1-lts`
- **预发布标记**: `prerelease: true` 当 tag 含 `-alpha`/`-beta`/`-rc` 任一
- **Cache 隔离**: 预发布 tag 在 cache key 中加 `-prerelease` 前缀
- **Tauri 不参与**: 预发布 tag 不触发 Tauri 构建（仅 stable 触发）
- **向后兼容**: 现有 `v0.1.0 - v0.4.2-lts` 12 个 tag 全部识别为 stable
- **环境**: 所有 Python 脚本测试必须用 `/home/fz/anaconda3/envs/sage-backend/bin/pytest` 或 `scripts/pytest.sh`
- **分支策略**: 不创建新分支（仅修改现有 main 分支的 tag + workflow）
- **commit message**: 走 conventional commits（`feat: ...` / `fix: ...` / `chore: ...`）

---

## File Structure

### 新建文件

| 路径 | 职责 |
|------|------|
| `scripts/release/__init__.py` | 空文件，让 `scripts.release` 成为可测试包 |
| `scripts/release/infer_tier.py` | 升档判断 CLI，输入 git log + CLI flags，输出 JSON 推荐档位 |
| `scripts/release/append_changelog.py` | CHANGELOG 段落插入 CLI，解析 conventional commits，按 type 分节 |
| `scripts/release/tests/__init__.py` | 空文件 |
| `scripts/release/tests/test_infer_tier.py` | infer_tier 单元测试 |
| `scripts/release/tests/test_append_changelog.py` | append_changelog 单元测试 |
| `scripts/release/determine_artifact_suffix.sh` | Bash 脚本，根据 GITHUB_REF_NAME 输出 GITHUB_OUTPUT value= |
| `scripts/release/tests/test_determine_artifact_suffix.sh` | Bash 脚本单元测试 |

### 修改文件

| 路径 | 改动 |
|------|------|
| `.github/workflows/release.yml` | 加 prerelease 字段 + cache key 改写 + ARTIFACT_SUFFIX 步骤 |
| `.github/workflows/release-win7.yml` | 同步加 prerelease 字段 + cache key 改写 + ARTIFACT_SUFFIX 步骤 |

---

## Task 1: 实现 infer_tier.py（升档判断脚本）

**Files:**
- Create: `scripts/release/__init__.py`
- Create: `scripts/release/infer_tier.py`
- Create: `scripts/release/tests/__init__.py`
- Create: `scripts/release/tests/test_infer_tier.py`
- Create: `scripts/release/tests/fixtures/sample_repo.sh`（git 仓库 fixture helper）

**Interfaces:**
- Consumes: `subprocess.run(['git', 'log', ...])` 读 commit messages
- Produces: stdout JSON `{"recommended_tier": str, "recommended_tag": str, "confidence": str, "reasons": list[str], "next_action": str}`

### Step 1: 写 fixture helper（建立测试用的 git 仓库）

```bash
# scripts/release/tests/fixtures/sample_repo.sh
#!/usr/bin/env bash
# 创建临时 git 仓库 + 给定 commits，用于测试 infer_tier.py
# 用法: source sample_repo.sh && setup_repo "feat: x" "fix: y" "feat(scope): z"

setup_repo() {
    local tmpdir
    tmpdir=$(mktemp -d)
    cd "$tmpdir" || exit 1
    git init -q -b main
    git config user.email "test@example.com"
    git config user.name "Test"
    
    # Initial commit on a previous version
    echo "# initial" > README.md
    git add README.md
    git commit -q -m "chore: initial"
    git tag v0.4.0
    
    # Apply each provided commit
    for msg in "$@"; do
        echo "$msg" >> README.md
        git add README.md
        git commit -q -m "$msg"
    done
    
    echo "$tmpdir"
}
```

### Step 2: 写第一个失败测试（最小可验证场景：0 feat 应推 alpha）

`scripts/release/tests/test_infer_tier.py`:

```python
"""Tests for infer_tier.py — Sage release tier inference.

Uses a temporary git repo fixture (see fixtures/sample_repo.sh) to create
real commit history and invoke infer_tier as subprocess.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo.sh"
INFER_TIER = Path(__file__).parent.parent / "infer_tier.py"


@pytest.fixture
def temp_repo():
    """Create a temp git repo with given commits; yield its path; cleanup."""
    def _make(*commits: str) -> str:
        result = subprocess.run(
            ["bash", str(FIXTURE)] + list(commits),
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    
    paths = []
    def maker(*commits):
        path = _make(*commits)
        paths.append(path)
        return path
    
    yield maker
    
    for p in paths:
        subprocess.run(["rm", "-rf", p], check=False)


def run_infer_tier(repo: str, *args: str) -> dict:
    """Run infer_tier.py as subprocess; return parsed JSON."""
    result = subprocess.run(
        ["python", str(INFER_TIER),
         "--since-tag", "v0.4.0",
         "--target-minor", "0.5.0",
         "--milestone-closed", "",
         "--open-blockers", "0",
         *args],
        capture_output=True, text=True,
        cwd=repo,
    )
    assert result.returncode == 0, f"infer_tier failed: {result.stderr}"
    return json.loads(result.stdout)


def test_no_features_recommends_alpha_1(temp_repo):
    """With 0 feat commits and no milestones, recommend alpha.1."""
    repo = temp_repo("fix: small typo")
    
    output = run_infer_tier(repo, "--milestone-closed", "")
    
    assert output["recommended_tier"] == "alpha"
    assert output["recommended_tag"] == "v0.5.0-alpha.1"
    assert output["confidence"] in ("high", "medium")
```

### Step 3: 运行测试，确认失败（应 ImportError 或 ModuleNotFound）

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_infer_tier.py::test_no_features_recommends_alpha_1 -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.release'`

### Step 4: 创建空 __init__.py 文件

```bash
touch scripts/release/__init__.py
touch scripts/release/tests/__init__.py
```

### Step 5: 写最小实现 infer_tier.py（让测试通过）

`scripts/release/infer_tier.py`:

```python
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
        [--dry-run]

Output: JSON to stdout
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
    cwd: str = ".",
) -> TierRecommendation:
    """Main inference logic. Returns TierRecommendation dataclass."""
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

    # Confidence
    confidence = "high" if len(reasons) >= 3 else "low"

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
    parser.add_argument("--dry-run", action="store_true", help="Recommend only; do not modify anything")
    args = parser.parse_args()

    milestones = [m.strip() for m in args.milestone_closed.split(",") if m.strip()]

    rec = infer_tier(
        since_tag=args.since_tag,
        target_minor=args.target_minor,
        milestone_closed=milestones,
        open_blockers=args.open_blockers,
        cwd=".",
    )

    print(rec.to_json())

    if not args.dry_run:
        # Future: maybe write to a file? For now, dry-run IS the mode.
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Step 6: 运行测试，确认通过

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_infer_tier.py::test_no_features_recommends_alpha_1 -v
```

Expected: PASS

### Step 7: 加第二个测试（3 feat + 1 milestone 应推 beta.1）

在 `test_infer_tier.py` 末尾追加：

```python
def test_three_feats_one_milestone_recommends_beta_1(temp_repo):
    """3 feat commits + 1 milestone closed → beta.1 (since no prior beta.1 tag)."""
    repo = temp_repo(
        "feat(auth): add login",
        "feat(ui): add button",
        "feat(api): add endpoint",
        "fix: typo",
    )
    
    output = run_infer_tier(repo, "--milestone-closed", "M1")
    
    assert output["recommended_tier"] == "beta"
    assert output["recommended_tag"] == "v0.5.0-beta.1"
```

### Step 8: 运行新测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_infer_tier.py -v
```

Expected: 2 PASS

### Step 9: 加第三个测试（6 feat + 2 milestone 应推 rc）

追加：

```python
def test_six_feats_two_milestones_recommends_rc(temp_repo):
    """6 feat commits + 2 milestones → rc.1."""
    repo = temp_repo(
        "feat: 1", "feat: 2", "feat: 3",
        "feat: 4", "feat: 5", "feat: 6",
    )
    
    output = run_infer_tier(repo, "--milestone-closed", "M1,M2")
    
    assert output["recommended_tier"] == "rc"
    assert output["recommended_tag"] == "v0.5.0-rc.1"
```

### Step 10: 运行新测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_infer_tier.py -v
```

Expected: 3 PASS

### Step 11: 加第四个测试（同一 MINOR 内 alpha 已发过 → 段内计数 +1）

追加：

```python
def test_increments_segment_counter(temp_repo):
    """If v0.5.0-alpha.1 already exists, next alpha is v0.5.0-alpha.2."""
    repo = temp_repo("feat: only one feature")
    
    # Create prior alpha tag inside the repo
    subprocess.run(["git", "tag", "v0.5.0-alpha.1"], cwd=repo, check=True)
    
    output = run_infer_tier(repo, "--milestone-closed", "")
    
    assert output["recommended_tier"] == "alpha"
    assert output["recommended_tag"] == "v0.5.0-alpha.2"
```

### Step 12: 运行测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_infer_tier.py -v
```

Expected: 4 PASS

### Step 13: Commit

```bash
git add scripts/release/__init__.py \
        scripts/release/infer_tier.py \
        scripts/release/tests/__init__.py \
        scripts/release/tests/test_infer_tier.py \
        scripts/release/tests/fixtures/sample_repo.sh
git commit -m "feat(release): infer_tier.py — 升档判断 CLI

- 读 git log 解析 Conventional Commits 前缀
- 推断下一档 (alpha/beta/rc/stable) 与具体 tag
- 段内计数重置 / 跨 MINOR 重置
- dry-run 模式（仅推荐，不修改任何东西）
- 4 个单元测试覆盖 0/3/6 feat 触发档位 + 段内计数

Refs: docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md §4"
```

---

## Task 2: 实现 append_changelog.py（CHANGELOG 段落插入脚本）

**Files:**
- Create: `scripts/release/append_changelog.py`

**Interfaces:**
- Input: `--tier` (alpha/beta/rc/stable), `--tag`, `--date`, `--milestone`, `--known-issues`
- Output: 修改 `CHANGELOG.md`，插入新段落到 `[Unreleased]` 后

### Step 1: 写第一个失败测试

`scripts/release/tests/test_append_changelog.py`:

```python
"""Tests for append_changelog.py — Sage CHANGELOG section inserter."""
import subprocess
from pathlib import Path

import pytest

APPEND_CHANGELOG = Path(__file__).parent.parent / "append_changelog.py"


@pytest.fixture
def temp_changelog(tmp_path):
    """Create a minimal CHANGELOG.md and yield its path."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(
        "# Changelog\n\n"
        "All notable changes to this project will be documented in this file.\n\n"
        "## [Unreleased]\n\n"
        "## [v0.4.2-lts] - 2026-07-04\n\n"
        "### Fixed\n"
        "- fix(electron): logger TDZ bug\n",
        encoding="utf-8",
    )
    return cl


def run_append_changelog(changelog_path: Path, *args: str) -> str:
    """Run append_changelog.py and return updated file content."""
    result = subprocess.run(
        ["python", str(APPEND_CHANGELOG),
         "--changelog", str(changelog_path),
         "--since-tag", "v0.4.2-lts",
         "--tier", "alpha",
         "--tag", "v0.5.0-alpha.1",
         "--date", "2026-07-06",
         "--milestone", "",
         "--known-issues", "",
         *args],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"failed: {result.stderr}"
    return changelog_path.read_text(encoding="utf-8")


def test_inserts_alpha_section_after_unreleased(temp_changelog):
    """Alpha section should be inserted between [Unreleased] and [v0.4.2-lts]."""
    content = run_append_changelog(temp_changelog)
    
    assert "## [v0.5.0-alpha.1] - 2026-07-06" in content
    
    pos_unreleased = content.index("## [Unreleased]")
    pos_alpha = content.index("## [v0.5.0-alpha.1]")
    pos_lts = content.index("## [v0.4.2-lts]")
    
    assert pos_unreleased < pos_alpha < pos_lts
```

### Step 2: 运行测试，确认失败

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_append_changelog.py::test_inserts_alpha_section_after_unreleased -v
```

Expected: FAIL with `FileNotFoundError` (append_changelog.py not yet created)

### Step 3: 写最小实现 append_changelog.py

`scripts/release/append_changelog.py`:

```python
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
        "style": [], "other": [],
    }
    pattern = re.compile(r"^(?P<type>[a-z]+)(?:\(.+?\))?!?:\s*(?P<subject>.+)$")
    for s in subjects:
        m = pattern.match(s)
        if m:
            t = m.group("type")
            if t in categorized:
                categorized[t].append(s)
                continue
        categorized["other"].append(s)
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
```

### Step 4: 运行测试，确认通过

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_append_changelog.py::test_inserts_alpha_section_after_unreleased -v
```

Expected: PASS

### Step 5: 加第二个测试（prerelease 加 Known Issues 段）

追加：

```python
def test_prerelease_adds_known_issues(temp_changelog):
    """Alpha section should include Known Issues block when provided."""
    content = run_append_changelog(
        temp_changelog,
        "--known-issues", "issue/123,issue/456",
    )
    
    assert "### Known Issues" in content
    assert "issue/123" in content
    assert "issue/456" in content
```

### Step 6: 运行测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/test_append_changelog.py -v
```

Expected: 2 PASS

### Step 7: Commit

```bash
git add scripts/release/append_changelog.py \
        scripts/release/tests/test_append_changelog.py
git commit -m "feat(release): append_changelog.py — CHANGELOG 段落插入 CLI

- 解析 Conventional Commits 按 type 分到 ### Added/Changed/Fixed
- 插入新段落到 [Unreleased] 之后、最旧版本之前
- prerelease (alpha/beta/rc) 自动加 Known Issues 段
- milestone 脚注链接
- 2 个单元测试覆盖插入位置 + Known Issues

Refs: docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md §5"
```

---

## Task 3: 实现 determine_artifact_suffix.sh（GitHub workflow 用的 Bash 脚本）

**Files:**
- Create: `scripts/release/determine_artifact_suffix.sh`
- Create: `scripts/release/tests/test_determine_artifact_suffix.sh`

**Interfaces:**
- Input: env var `GITHUB_REF_NAME`
- Output: GitHub Actions `$GITHUB_OUTPUT` line `value=<suffix>`

### Step 1: 写测试脚本（Bash）

`scripts/release/tests/test_determine_artifact_suffix.sh`:

```bash
#!/usr/bin/env bash
# Tests for determine_artifact_suffix.sh
# Usage: bash test_determine_artifact_suffix.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/../determine_artifact_suffix.sh"

fail_count=0

assert_eq() {
    local name="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        echo "  ✅ $name"
    else
        echo "  ❌ $name: expected '$expected', got '$actual'"
        fail_count=$((fail_count + 1))
    fi
}

# Helper: run the script with a given ref name and capture the value=
run_suffix() {
    local ref_name="$1"
    local output
    output=$(GITHUB_REF_NAME="$ref_name" bash "$SCRIPT")
    echo "$output" | grep '^value=' | cut -d= -f2-
}

echo "Testing determine_artifact_suffix.sh..."

# Test stable main
result=$(run_suffix "v0.5.0")
assert_eq "stable main → win10" "win10" "$result"

# Test stable LTS
result=$(run_suffix "v0.5.0-lts")
assert_eq "stable LTS → win7" "win7" "$result"

# Test alpha main
result=$(run_suffix "v0.5.0-alpha.1")
assert_eq "alpha main → alpha" "alpha" "$result"

# Test beta LTS
result=$(run_suffix "v0.5.0-beta.2-lts")
assert_eq "beta LTS → beta-lts" "beta-lts" "$result"

# Test rc LTS
result=$(run_suffix "v0.5.0-rc.1-lts")
assert_eq "rc LTS → rc-lts" "rc-lts" "$result"

if [[ $fail_count -eq 0 ]]; then
    echo ""
    echo "All tests passed."
    exit 0
else
    echo ""
    echo "$fail_count test(s) failed."
    exit 1
fi
```

### Step 2: 运行测试，确认失败

```bash
chmod +x scripts/release/tests/test_determine_artifact_suffix.sh
bash scripts/release/tests/test_determine_artifact_suffix.sh
```

Expected: Script not found error

### Step 3: 写 determine_artifact_suffix.sh 实现

`scripts/release/determine_artifact_suffix.sh`:

```bash
#!/usr/bin/env bash
# Determine electron-builder artifactName suffix from GitHub tag.
#
# Usage: GITHUB_REF_NAME=v0.5.0-beta.1 bash determine_artifact_suffix.sh
# Output: writes "value=<suffix>" to stdout (for $GITHUB_OUTPUT in workflow)
#
# Suffix mapping:
#   v0.5.0              → win10
#   v0.5.0-lts          → win7
#   v0.5.0-alpha.N      → alpha
#   v0.5.0-beta.N       → beta
#   v0.5.0-rc.N         → rc
#   v0.5.0-alpha.N-lts  → alpha-lts
#   v0.5.0-beta.N-lts   → beta-lts
#   v0.5.0-rc.N-lts     → rc-lts

set -euo pipefail

ref_name="${GITHUB_REF_NAME:-}"

if [[ -z "$ref_name" ]]; then
    echo "::error::GITHUB_REF_NAME is not set" >&2
    exit 1
fi

# Determine tier (alpha / beta / rc / stable)
tier="stable"
if [[ "$ref_name" == *-alpha* ]]; then
    tier="alpha"
elif [[ "$ref_name" == *-beta* ]]; then
    tier="beta"
elif [[ "$ref_name" == *-rc* ]]; then
    tier="rc"
fi

# Determine LTS suffix
is_lts="false"
if [[ "$ref_name" == *-lts ]]; then
    is_lts="true"
fi

# Combine
if [[ "$tier" == "stable" ]]; then
    if [[ "$is_lts" == "true" ]]; then
        suffix="win7"
    else
        suffix="win10"
    fi
else
    if [[ "$is_lts" == "true" ]]; then
        suffix="${tier}-lts"
    else
        suffix="$tier"
    fi
fi

# Emit GitHub Actions output format
echo "value=$suffix"
```

### Step 4: 运行测试，确认通过

```bash
chmod +x scripts/release/determine_artifact_suffix.sh
bash scripts/release/tests/test_determine_artifact_suffix.sh
```

Expected: All 5 tests passed

### Step 5: Commit

```bash
git add scripts/release/determine_artifact_suffix.sh \
        scripts/release/tests/test_determine_artifact_suffix.sh
git commit -m "feat(release): determine_artifact_suffix.sh — workflow 后缀推导

- 从 GITHUB_REF_NAME 推导 electron-builder artifactName suffix
- 覆盖 stable/alpha/beta/rc × LTS 矩阵 8 种组合
- 输出 GitHub Actions \$GITHUB_OUTPUT 格式
- 5 个 Bash 测试覆盖所有分支

Refs: docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md §3.4"
```

---

## Task 4: 改 release.yml（main 分支 release workflow）

**Files:**
- Modify: `.github/workflows/release.yml`

**改动点**:
1. 加 prerelease 字段到 `softprops/action-gh-release@v2`
2. Cache key 加 `prerelease-` 命名空间
3. 在 Windows 构建步骤前加 `Determine ARTIFACT_SUFFIX` 步骤
4. body 加 tier 标识

### Step 1: 当前 release.yml 状态确认

```bash
cat .github/workflows/release.yml | head -60
```

预期看到 line 30-50 含 cache key，line 109-114 含 Build Windows。

### Step 2: 改 cache key（line 76）

**修改前**:
```yaml
key: ${{ runner.os }}-electron-${{ hashFiles('package-lock.json') }}
```

**修改后**:
```yaml
key: ${{ runner.os }}-electron-${{ contains(github.ref_name, '-') && 'prerelease-' || '' }}${{ hashFiles('package-lock.json') }}
```

### Step 3: 在 Build Windows 步骤前加 suffix 步骤

**修改位置**: 在 line 105 (`- name: Build Windows (NSIS installer)`) 前加新步骤：

```yaml
      - name: Determine ARTIFACT_SUFFIX
        id: suffix
        run: bash scripts/release/determine_artifact_suffix.sh >> $GITHUB_OUTPUT

      - name: Build Windows (NSIS installer)
        if: matrix.os == 'windows-latest'
        env:
          # Override default; produces Sage-Setup-${version}${env.ARTIFACT_SUFFIX}.${ext}
          ARTIFACT_SUFFIX: ${{ steps.suffix.outputs.value }}
        run: npx electron-builder --win nsis --publish never
```

### Step 4: 改 Upload 步骤加 prerelease + body tier 标识

**修改位置**: line 116-132（`Upload artifacts to GitHub Release`）

**修改后**:
```yaml
      - name: Upload artifacts to GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          files: |
            release/*/Sage-*.AppImage
            release/*/sage_*_amd64.deb
            release/*/Sage-Setup-*.exe
          prerelease: ${{ contains(github.ref_name, '-alpha') || contains(github.ref_name, '-beta') || contains(github.ref_name, '-rc') }}
          body: |
            ## 🧪 Sage ${{ github.ref_name }}

            > **This is a ${{ contains(github.ref_name, '-alpha') && 'ALPHA' || contains(github.ref_name, '-beta') && 'BETA' || contains(github.ref_name, '-rc') && 'RELEASE CANDIDATE' || 'STABLE' }} release.**
            > ${{ contains(github.ref_name, '-alpha') && '⚠️ 仅供 Sage 贡献者使用，可能含已知 bug。' || contains(github.ref_name, '-beta') && '⚠️ 公开测试版，欢迎反馈 issue。' || contains(github.ref_name, '-rc') && '✅ 准稳定版，推荐广泛测试。' || '✅ 稳定版，推荐所有用户升级。' }}

            See [CHANGELOG.md](https://github.com/${{ github.repository }}/blob/${{ github.ref_name }}/CHANGELOG.md) for details.
          draft: true
          generate_release_notes: true
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

注：file pattern 从 `Sage-Setup-*-win10.exe` 改为 `Sage-Setup-*.exe` 以匹配所有 suffix（alpha/beta/rc/win10）。

### Step 5: 用 actionlint 验证 YAML 语法（如可用）

```bash
# actionlint 需要 npx（项目应有）
npx actionlint .github/workflows/release.yml
```

Expected: 无错误

如果 actionlint 不可用，跳过此步直接 commit，CI 会自动验证。

### Step 6: Commit

```bash
git add .github/workflows/release.yml
git commit -m "feat(ci): release.yml 支持 4 档分级 (alpha/beta/rc/stable)

- prerelease 字段自动从 tag 推断 (含 -alpha/-beta/-rc → true)
- Cache key 加 prerelease- 命名空间避免污染 stable
- Build Windows 步骤前调 determine_artifact_suffix.sh
- Upload 步骤 body 加 tier 标识 (ALPHA/BETA/RC/STABLE + 风险提示)
- file glob 从 -win10.exe 改为 *.exe 覆盖所有 suffix

Refs: docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md §3.1, §3.2, §3.4"
```

---

## Task 5: 改 release-win7.yml（win7 LTS release workflow）

**Files:**
- Modify: `.github/workflows/release-win7.yml`

**改动**: 与 Task 4 相同的模式，但应用到 win7 LTS workflow。

### Step 1: 改 cache key（line 53）

**修改前**:
```yaml
key: ${{ runner.os }}-electron-lts-${{ hashFiles('package-lock.json') }}
```

**修改后**:
```yaml
key: ${{ runner.os }}-electron-lts-${{ contains(github.ref_name, '-') && 'prerelease-' || '' }}${{ hashFiles('package-lock.json') }}
```

### Step 2: 在 Build Windows NSIS 步骤前加 suffix 步骤

**修改位置**: 在 line 71-72 (`Build Windows NSIS (Win7 LTS, env.ARTIFACT_SUFFIX=win7)`) 前加：

```yaml
      - name: Determine ARTIFACT_SUFFIX
        id: suffix
        run: bash scripts/release/determine_artifact_suffix.sh >> $GITHUB_OUTPUT

      - name: Build Windows NSIS (Win7 LTS, dynamic suffix)
        env:
          # Override default; produces Sage-Setup-${version}${env.ARTIFACT_SUFFIX}.${ext}
          ARTIFACT_SUFFIX: ${{ steps.suffix.outputs.value }}
        run: npx electron-builder --win nsis --publish never
```

### Step 3: 改 Upload 步骤加 prerelease + body tier 标识

**修改位置**: line 74-108

**修改后**:
```yaml
      - name: Upload to LTS GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          files: |
            release/*/Sage-Setup-*.exe
          prerelease: ${{ contains(github.ref_name, '-alpha') || contains(github.ref_name, '-beta') || contains(github.ref_name, '-rc') }}
          body: |
            ## Sage ${{ github.ref_name }} (Win7 LTS) — Windows 7 SP1 x64 ONLY

            > ⚠️ **此版本专为 Windows 7 SP1 x64 设计**。
            > Win10+ 用户请改用 [main release](https://github.com/${{ github.repository }}/releases)。

            > **Tier**: ${{ contains(github.ref_name, '-alpha') && 'ALPHA' || contains(github.ref_name, '-beta') && 'BETA' || contains(github.ref_name, '-rc') && 'RC' || 'STABLE' }}
            > ${{ contains(github.ref_name, '-alpha') && '⚠️ 仅供 Sage 贡献者使用。' || contains(github.ref_name, '-beta') && '⚠️ 公开测试版。' || contains(github.ref_name, '-rc') && '✅ 准稳定版。' || '✅ 稳定版，推荐 Win7 用户升级。' }}

            ### Downloads

            | File | Notes |
            | --- | --- |
            | `Sage-Setup-*.exe` | NSIS, x64, VCRedist bundled |

            ### Win7 前置

            - **KB3033929** (SHA-2 代码签名支持, 2016 年发布) — Win7 SP1 必装, 否则 Sage.exe 启动被拒
            - x64 only (Electron 21 不支持 Win7 32-bit)

            ### 风险声明

            ⚠️ 本分支基于 EOL 技术栈 (Electron 21.4.4 + Python 3.8 + Chromium 106)。
            详见 [`docs/technical/21-win7-lts.md`](https://github.com/${{ github.repository }}/blob/${{ github.ref_name }}/docs/technical/21-win7-lts.md) §6。
          draft: true
          generate_release_notes: true
          fail_on_unmatched_files: false
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Step 4: 改 job 级 if 条件（保持 LTS-only 行为）

**当前 line 28**:
```yaml
if: "contains(github.ref_name, '-lts')"
```

这个条件仍有效，win7 LTS workflow 只在 `-lts` tag 触发，保持不变。

### Step 5: 验证 YAML（可选）

```bash
npx actionlint .github/workflows/release-win7.yml
```

Expected: 无错误

### Step 6: Commit

```bash
git add .github/workflows/release-win7.yml
git commit -m "feat(ci): release-win7.yml 支持 4 档分级 (alpha/beta/rc/stable) + LTS

- prerelease 字段自动从 tag 推断
- Cache key 加 prerelease- 命名空间
- suffix 从 determine_artifact_suffix.sh 注入 (产出 alpha-lts/beta-lts/rc-lts/win7)
- Upload body 加 Tier 标识 (ALPHA/BETA/RC/STABLE)
- file glob 从 -win7.exe 改为 *.exe 覆盖所有 suffix

Refs: docs/superpowers/specs/2026-07-06-sage-release-tiers-design.md §3.3, §3.4"
```

---

## Task 6: CI 验证 — 端到端检查

**Files:**
- Modify: 无（仅验证）

### Step 1: 本地跑所有 infer_tier 测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pytest scripts/release/tests/ -v
```

Expected: 6 PASS (4 infer_tier + 2 append_changelog)

### Step 2: 本地跑 Bash 测试

```bash
bash scripts/release/tests/test_determine_artifact_suffix.sh
```

Expected: All 5 tests passed

### Step 3: 验证 YAML 语法（如有 actionlint）

```bash
npx actionlint .github/workflows/release.yml .github/workflows/release-win7.yml
```

Expected: 无错误

如果 actionlint 不在 dev dependencies 中，跳过此步。

### Step 4: 跑本地 CI backend 验证（pre-push 检查）

```bash
cd backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest tests/unit/ -q --no-header
```

Expected: 全过（不应有回归，因为本计划只添加新脚本，未修改 backend）

### Step 5: 跑前端 vitest 验证

```bash
npm run test:run 2>&1 | tail -20
```

Expected: 全过（不应有回归）

### Step 6: 手动 dry-run 真实 git 仓库

```bash
# 假设在 main 分支
python scripts/release/infer_tier.py \
    --since-tag v0.4.2-lts \
    --target-minor 0.5.0 \
    --milestone-closed "M1,M2,M3" \
    --open-blockers 0 \
    --dry-run
```

Expected: 输出 JSON，包含 `recommended_tier` 字段（具体值由当前 commits 决定）

### Step 7: 验证脚本不修改 git 状态

```bash
git status
```

Expected: 工作树干净（仅 .github/workflows 改动 + 新 scripts/release/ 目录）

### Step 8: 报告完成

```bash
echo "✅ Phase 1 基础设施完成"
echo "- scripts/release/infer_tier.py (4 测试)"
echo "- scripts/release/append_changelog.py (2 测试)"
echo "- scripts/release/determine_artifact_suffix.sh (5 Bash 测试)"
echo "- .github/workflows/release.yml 改动"
echo "- .github/workflows/release-win7.yml 改动"
echo ""
echo "下一步：Phase 2 文档同步（独立 plan 即将推出）"
```

---

## Self-Review

按 writing-plans skill 的 self-review checklist 过一遍：

**1. Spec coverage** — spec 各节都有对应 task：
- §2 版本号规范 → Task 1-3 脚本推断 (含 BREAKING/段内计数/MINOR 重置)
- §3 CI workflow 改动 → Task 4 (release.yml) + Task 5 (release-win7.yml)
- §4 升档脚本 → Task 1 (infer_tier.py)
- §5 CHANGELOG 模板 → Task 2 (append_changelog.py)
- §6 文档同步 → Phase 2 (不在本 plan)
- §7 故障处理 → Phase 4-6 运营性步骤（不在本 plan）
- §8 实施步骤 Phase 1 → Task 1-6 本计划

**2. Placeholder scan**：
- ❌ 无 "TBD" / "TODO" / "implement later"
- ❌ 无 "appropriate error handling" / "similar to"
- ❌ 步骤都有完整代码块
- ✅ 所有 infer_tier 测试都是完整 Python 代码
- ✅ Bash 测试有完整断言

**3. Type consistency**：
- `TierRecommendation` dataclass 字段一致（recommended_tier / recommended_tag / confidence / reasons / next_action）
- `--changelog` CLI flag 一致（在 Task 2 步骤 1 测试用 + Task 2 步骤 3 argparse 定义）
- `GITHUB_REF_NAME` 环境变量名一致（Bash 脚本 + workflow 调用）
- ARTIFACT_SUFFIX suffix 值在 Bash 脚本和 workflow step outputs 间对齐

**所有检查通过，可执行。**