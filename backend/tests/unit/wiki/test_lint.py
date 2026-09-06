"""Unit tests for backend.wiki.lint."""
from pathlib import Path

import pytest

from backend.wiki.lint import (
    LintIssue,
    LintResult,
    LintSeverity,
    LintType,
    WikiLint,
)


def _make_project(tmp_path: Path, files: dict) -> Path:
    """Create a project tree under tmp_path.

    ``files`` is a mapping from relative path (under tmp_path) to content.
    Directories are created implicitly from file paths.
    """
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


class TestLintResult:
    def test_empty_result(self) -> None:
        r = LintResult()
        assert r.total == 0
        assert r.by_severity == {"error": 0, "warning": 0, "info": 0}

    def test_by_severity_counts(self) -> None:
        r = LintResult(
            issues=[
                LintIssue(
                    type=LintType.ORPHAN_PAGE, severity=LintSeverity.ERROR,
                    page="a.md", detail="x",
                ),
                LintIssue(
                    type=LintType.ORPHAN_PAGE, severity=LintSeverity.WARNING,
                    page="b.md", detail="y",
                ),
                LintIssue(
                    type=LintType.ORPHAN_PAGE, severity=LintSeverity.WARNING,
                    page="c.md", detail="z",
                ),
                LintIssue(
                    type=LintType.ORPHAN_PAGE, severity=LintSeverity.INFO,
                    page="d.md", detail="w",
                ),
            ]
        )
        assert r.total == 4
        assert r.by_severity == {"error": 1, "warning": 2, "info": 1}

    def test_to_dict_shape(self) -> None:
        issue = LintIssue(
            type=LintType.WIKILINK_BROKEN,
            severity=LintSeverity.WARNING,
            page="wiki/entities/foo.md",
            detail="断链: [[missing]]",
            broken_target="missing",
            suggested_target="创建页面: missing.md",
        )
        r = LintResult(issues=[issue])
        d = r.to_dict()
        assert d["total"] == 1
        assert d["by_severity"]["warning"] == 1
        assert len(d["issues"]) == 1
        i = d["issues"][0]
        assert i["type"] == "wikilink_broken"
        assert i["severity"] == "warning"
        assert i["page"] == "wiki/entities/foo.md"
        assert i["broken_target"] == "missing"
        assert i["suggested_target"] == "创建页面: missing.md"


class TestCheckStructure:
    def test_all_dirs_present(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\n",
            "wiki/concepts/b.md": "---\ntitle: B\n---\n",
            "wiki/sources/c.md": "---\ntitle: C\n---\n",
            "wiki/queries/d.md": "---\ntitle: D\n---\n",
            "wiki/schema.md": "---\ntitle: Schema\n---\n",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_structure()
        assert issues == []

    def test_missing_dirs_and_files(self, tmp_path: Path) -> None:
        # Empty project: nothing exists
        _make_project(tmp_path, {})
        lint = WikiLint(tmp_path)
        issues = lint.check_structure()

        # Expect 4 missing dirs + 1 missing file = 5
        types = [i.type for i in issues]
        assert types.count(LintType.REQUIRED_DIR) == 4
        assert types.count(LintType.REQUIRED_FILE) == 1
        assert all(i.severity == LintSeverity.ERROR for i in issues)

    def test_partial_structure(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\n",
            "wiki/schema.md": "---\ntitle: Schema\n---\n",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_structure()

        # Missing: concepts, sources, queries (3 dirs)
        missing_dirs = {
            i.page for i in issues if i.type == LintType.REQUIRED_DIR
        }
        assert missing_dirs == {
            "wiki/concepts",
            "wiki/sources",
            "wiki/queries",
        }


class TestCheckFrontmatter:
    def test_no_wiki_dir(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {})
        lint = WikiLint(tmp_path)
        assert lint.check_frontmatter() == []

    def test_all_good(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: Page A\n---\nbody",
            "wiki/concepts/b.md": "---\ntitle: Page B\ntags: [x]\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        assert lint.check_frontmatter() == []

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "Just some markdown without frontmatter",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_frontmatter()
        assert len(issues) == 1
        assert issues[0].type == LintType.FRONTMATTER_MISSING
        assert issues[0].severity == LintSeverity.WARNING
        assert issues[0].page == "wiki/entities/a.md"

    def test_missing_title(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntags: [x]\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_frontmatter()
        assert len(issues) == 1
        assert issues[0].type == LintType.FRONTMATTER_TITLE

    def test_empty_title(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle:\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_frontmatter()
        assert len(issues) == 1
        assert issues[0].type == LintType.FRONTMATTER_TITLE

    def test_unclosed_frontmatter(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: X\nbody without closing fence",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_frontmatter()
        assert len(issues) == 1
        assert issues[0].type == LintType.FRONTMATTER_MISSING


class TestCheckWikilinks:
    def test_no_wikilinks(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nplain text",
        })
        lint = WikiLint(tmp_path)
        assert lint.check_wikilinks() == []

    def test_valid_wikilink(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nSee [[b]] for details.",
            "wiki/entities/b.md": "---\ntitle: B\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        assert lint.check_wikilinks() == []

    def test_broken_wikilink(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nSee [[missing]] for more.",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_wikilinks()
        assert len(issues) == 1
        i = issues[0]
        assert i.type == LintType.WIKILINK_BROKEN
        assert i.severity == LintSeverity.WARNING
        assert i.broken_target == "missing"
        assert "missing.md" in (i.suggested_target or "")

    def test_wikilink_with_alias(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nSee [[b|label]] for more.",
            "wiki/entities/b.md": "---\ntitle: B\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        # [[b|label]] should resolve to b
        assert lint.check_wikilinks() == []

    def test_wikilink_with_anchor(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nSee [[b#section]] for more.",
            "wiki/entities/b.md": "---\ntitle: B\n---\nbody\n## Section\n",
        })
        lint = WikiLint(tmp_path)
        # The pattern strips anchors; 'b' resolves
        assert lint.check_wikilinks() == []

    def test_cross_directory_wikilink(self, tmp_path: Path) -> None:
        # [[concepts/x]] from entities/a.md — should resolve
        _make_project(tmp_path, {
            "wiki/entities/a.md": (
                "---\ntitle: A\n---\nSee [[concepts/x]] for details."
            ),
            "wiki/concepts/x.md": "---\ntitle: X\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        assert lint.check_wikilinks() == []


class TestCheckOrphans:
    def test_exempt_pages_not_reported(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/schema.md": "---\ntitle: Schema\n---\n",
            "wiki/overview.md": "---\ntitle: Overview\n---\n",
        })
        lint = WikiLint(tmp_path)
        assert lint.check_orphans() == []

    def test_unreferenced_page_reported(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_orphans()
        assert len(issues) == 1
        assert issues[0].type == LintType.ORPHAN_PAGE
        assert issues[0].severity == LintSeverity.INFO
        assert issues[0].page == "wiki/entities/a.md"

    def test_referenced_page_not_reported(self, tmp_path: Path) -> None:
        # Page `a` is referenced (incoming wikilink) from `b`, so it's not orphan
        _make_project(tmp_path, {
            "wiki/entities/a.md": "---\ntitle: A\n---\nbody",
            "wiki/entities/b.md": "---\ntitle: B\n---\nSee [[a]]",
        })
        lint = WikiLint(tmp_path)
        issues = lint.check_orphans()
        # `b` is still orphan (nothing links to it), but `a` is not
        orphan_pages = {i.page for i in issues}
        assert "wiki/entities/a.md" not in orphan_pages
        assert "wiki/entities/b.md" in orphan_pages


class TestCheckAll:
    def test_check_all_combines_everything(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            # schema.md + overview.md present → no required_file error
            "wiki/schema.md": "---\ntitle: Schema\n---\n",
            "wiki/overview.md": "---\ntitle: Overview\n---\n",
            # Missing: entities/concepts/sources/queries → 4 structure errors
            # orphan: schema.md + overview.md are exempt
        })
        lint = WikiLint(tmp_path)
        result = lint.check_all()

        assert result.total >= 4  # at least 4 missing dirs
        assert result.by_severity["error"] >= 4

    def test_check_all_clean_project(self, tmp_path: Path) -> None:
        # Every non-exempt page must be referenced (incoming wikilink) from another
        _make_project(tmp_path, {
            "wiki/schema.md": "---\ntitle: Schema\n---\n",
            "wiki/overview.md": "---\ntitle: Overview\n---\n",
            "wiki/entities/a.md": (
                "---\ntitle: A\n---\nSee [[b]] and [[schema]]."
            ),
            "wiki/entities/b.md": "---\ntitle: B\n---\nSee [[a]] and [[c]]",
            "wiki/concepts/c.md": "---\ntitle: C\n---\nSee [[a]] and [[s]]",
            "wiki/sources/s.md": "---\ntitle: S\n---\nSee [[a]] and [[q]]",
            "wiki/queries/q.md": "---\ntitle: Q\n---\nSee [[a]]",
        })
        lint = WikiLint(tmp_path)
        result = lint.check_all()
        assert result.total == 0


class TestEdgeCases:
    def test_path_traversal_wikilink_reported_broken(self, tmp_path: Path) -> None:
        # Path traversal attempt in wikilink target should not escape wiki/
        _make_project(tmp_path, {
            "wiki/entities/a.md": (
                "---\ntitle: A\n---\n[[../../etc/passwd]]"
            ),
            "wiki/schema.md": "---\ntitle: Schema\n---\n",
        })
        lint = WikiLint(tmp_path)
        # The link should be reported as broken (not resolve to real file)
        issues = lint.check_wikilinks()
        assert any(
            i.type == LintType.WIKILINK_BROKEN
            and "../../etc/passwd" in (i.broken_target or "")
            for i in issues
        )

    def test_unicode_page_title(self, tmp_path: Path) -> None:
        _make_project(tmp_path, {
            "wiki/entities/中文页.md": "---\ntitle: 中文页\n---\nbody",
        })
        lint = WikiLint(tmp_path)
        # Orphan because unreferenced, but not a frontmatter/structure issue
        issues_fm = lint.check_frontmatter()
        assert issues_fm == []
        issues_orphan = lint.check_orphans()
        assert len(issues_orphan) == 1
        assert issues_orphan[0].page == "wiki/entities/中文页.md"

    def test_non_utf8_file_skipped(self, tmp_path: Path) -> None:
        # Write a file with invalid UTF-8 bytes — should be skipped, not crash
        (tmp_path / "wiki" / "entities").mkdir(parents=True)
        bad = tmp_path / "wiki" / "entities" / "bad.md"
        bad.write_bytes(b"\xff\xfe\xfd")
        lint = WikiLint(tmp_path)
        # Should not raise; frontmatter check returns issue for unparseable file
        issues = lint.check_frontmatter()
        assert isinstance(issues, list)


@pytest.mark.parametrize("severity", ["error", "warning", "info"])
def test_lint_issue_severity_roundtrip(severity: str) -> None:
    issue = LintIssue(
        type=LintType.ORPHAN_PAGE,
        severity=LintSeverity(severity),
        page="x.md",
        detail="x",
    )
    d = issue.to_dict()
    assert d["severity"] == severity
    assert LintSeverity(d["severity"]) == LintSeverity(severity)
