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


def test_stable_omits_known_issues(temp_changelog):
    """Stable tier must NOT include Known Issues block (spec §5.3)."""
    content = run_append_changelog(
        temp_changelog,
        "--tier", "stable",
        "--tag", "v0.5.0",
        "--known-issues", "issue/123,issue/456",
    )

    assert "### Known Issues" not in content


def test_preserves_unreleased_section(temp_changelog):
    """The ## [Unreleased] header must remain unchanged after insertion (spec §5.5)."""
    content = run_append_changelog(temp_changelog)

    # Unreleased header is still present and intact
    assert "## [Unreleased]" in content
    # And it still appears before the new section
    pos_unreleased = content.index("## [Unreleased]")
    pos_alpha = content.index("## [v0.5.0-alpha.1]")
    assert pos_unreleased < pos_alpha


def test_prerelease_adds_known_issues(temp_changelog):
    """Alpha section should include Known Issues block when provided."""
    content = run_append_changelog(
        temp_changelog,
        "--known-issues", "issue/123,issue/456",
    )

    assert "### Known Issues" in content
    assert "issue/123" in content
    assert "issue/456" in content
