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


def test_six_feats_two_milestones_recommends_rc(temp_repo):
    """6 feat commits + 2 milestones → rc.1."""
    repo = temp_repo(
        "feat: 1", "feat: 2", "feat: 3",
        "feat: 4", "feat: 5", "feat: 6",
    )

    output = run_infer_tier(repo, "--milestone-closed", "M1,M2")

    assert output["recommended_tier"] == "rc"
    assert output["recommended_tag"] == "v0.5.0-rc.1"


def test_increments_segment_counter(temp_repo):
    """If v0.5.0-alpha.1 already exists, next alpha is v0.5.0-alpha.2."""
    repo = temp_repo("feat: only one feature")

    # Create prior alpha tag inside the repo
    subprocess.run(["git", "tag", "v0.5.0-alpha.1"], cwd=repo, check=True)

    output = run_infer_tier(repo, "--milestone-closed", "")

    assert output["recommended_tier"] == "alpha"
    assert output["recommended_tag"] == "v0.5.0-alpha.2"