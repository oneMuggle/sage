"""Unit tests for backend.wiki.review."""
from pathlib import Path

import pytest

from backend.wiki.review import (
    ReviewItem,
    ReviewResult,
    ReviewType,
    WikiReview,
    _jaccard,
    _stable_id,
    _strip_frontmatter,
    _tokenize,
)


def _make_project(tmp_path: Path, files: dict) -> Path:
    """Create a project tree under tmp_path.

    ``files`` maps relative path -> content. Directories created implicitly.
    """
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# ============================================================================
# Helpers
# ============================================================================


class TestHelpers:
    def test_stable_id_deterministic(self) -> None:
        a = _stable_id(ReviewType.MISSING_PAGE, "foo")
        b = _stable_id(ReviewType.MISSING_PAGE, "foo")
        assert a == b
        assert a.startswith("rv-")
        assert len(a) == 3 + 16  # "rv-" + 16 hex

    def test_stable_id_differs_by_type(self) -> None:
        a = _stable_id(ReviewType.MISSING_PAGE, "foo")
        b = _stable_id(ReviewType.DUPLICATE, "foo")
        assert a != b

    def test_stable_id_differs_by_key(self) -> None:
        a = _stable_id(ReviewType.MISSING_PAGE, "foo")
        b = _stable_id(ReviewType.MISSING_PAGE, "bar")
        assert a != b

    def test_strip_frontmatter(self) -> None:
        text = "---\ntitle: Foo\ncreated: 2026-09-06\n---\nBody here"
        fields, body = _strip_frontmatter(text)
        assert fields["title"] == "Foo"
        assert fields["created"] == "2026-09-06"
        assert "Body here" in body

    def test_strip_frontmatter_no_frontmatter(self) -> None:
        fields, body = _strip_frontmatter("just text")
        assert fields == {}
        assert body == "just text"

    def test_strip_frontmatter_unclosed(self) -> None:
        fields, body = _strip_frontmatter("---\ntitle: X\nno end")
        assert fields == {}
        assert body == "---\ntitle: X\nno end"

    def test_tokenize(self) -> None:
        tokens = _tokenize("Hello, 世界! This is a test.")
        assert "hello" in tokens
        assert "世界" in tokens
        # Single-letter tokens filtered out
        assert "a" not in tokens

    def test_jaccard_identical(self) -> None:
        assert _jaccard(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_jaccard_disjoint(self) -> None:
        assert _jaccard(["a"], ["b"]) == 0.0

    def test_jaccard_partial(self) -> None:
        score = _jaccard(["a", "b", "c"], ["b", "c", "d"])
        assert abs(score - 0.5) < 1e-9

    def test_jaccard_empty(self) -> None:
        assert _jaccard([], ["a"]) == 0.0
        assert _jaccard([], []) == 0.0


# ============================================================================
# ReviewItem / ReviewResult
# ============================================================================


class TestDataClasses:
    def test_review_item_to_dict(self) -> None:
        item = ReviewItem(
            id="rv-abc",
            type=ReviewType.MISSING_PAGE,
            title="t",
            description="d",
            affected_pages=["a", "b"],
            confidence=0.8,
            detail="x",
            suggestion="s",
        )
        d = item.to_dict()
        assert d["id"] == "rv-abc"
        assert d["type"] == "missing-page"
        assert d["affected_pages"] == ["a", "b"]
        assert d["confidence"] == 0.8

    def test_review_item_to_dict_mutability(self) -> None:
        """to_dict 返回的 affected_pages 是拷贝，修改不影响原对象"""
        item = ReviewItem(
            id="rv-1",
            type=ReviewType.SUGGESTION,
            title="t",
            description="d",
            affected_pages=["a"],
            confidence=0.5,
        )
        d = item.to_dict()
        d["affected_pages"].append("z")
        assert item.affected_pages == ["a"]

    def test_review_result_empty(self) -> None:
        r = ReviewResult()
        assert r.total == 0
        assert r.by_type == {
            "duplicate": 0,
            "contradiction": 0,
            "missing-page": 0,
            "confirm": 0,
            "suggestion": 0,
        }

    def test_review_result_by_type_counts(self) -> None:
        r = ReviewResult(
            items=[
                ReviewItem(
                    id="a",
                    type=ReviewType.DUPLICATE,
                    title="t",
                    description="d",
                    affected_pages=[],
                    confidence=0.5,
                ),
                ReviewItem(
                    id="b",
                    type=ReviewType.DUPLICATE,
                    title="t2",
                    description="d2",
                    affected_pages=[],
                    confidence=0.5,
                ),
                ReviewItem(
                    id="c",
                    type=ReviewType.CONTRADICTION,
                    title="t3",
                    description="d3",
                    affected_pages=[],
                    confidence=0.5,
                ),
            ]
        )
        assert r.total == 3
        assert r.by_type["duplicate"] == 2
        assert r.by_type["contradiction"] == 1
        assert r.by_type["missing-page"] == 0

    def test_review_result_to_dict_shape(self) -> None:
        r = ReviewResult()
        d = r.to_dict()
        assert set(d.keys()) == {"total", "by_type", "items"}
        assert d["total"] == 0
        assert isinstance(d["items"], list)


# ============================================================================
# Missing pages
# ============================================================================


class TestCheckMissingPages:
    def test_no_wiki_dir(self, tmp_path: Path) -> None:
        reviewer = WikiReview(tmp_path)
        assert reviewer.check_missing_pages() == []

    def test_all_links_resolve(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\n---\nSee [[b]]",
                "wiki/b.md": "---\ntitle: B\n---\nHello",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_missing_pages()
        assert items == []

    def test_broken_link_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "---\ntitle: A\n---\nSee [[missing-page]]"},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_missing_pages()
        assert len(items) == 1
        assert items[0].type == ReviewType.MISSING_PAGE
        assert "missing-page" in items[0].title
        assert items[0].affected_pages == ["wiki/a.md"]
        assert items[0].confidence == 1.0

    def test_multiple_sources_same_target(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\n---\n[[missing]]",
                "wiki/b.md": "---\ntitle: B\n---\n[[missing]]",
                "wiki/c.md": "---\ntitle: C\n---\n[[missing]]",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_missing_pages()
        assert len(items) == 1
        assert sorted(items[0].affected_pages) == [
            "wiki/a.md",
            "wiki/b.md",
            "wiki/c.md",
        ]

    def test_wikilink_with_alias_still_checks_target(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "---\ntitle: A\n---\n[[target|Display text]]"},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_missing_pages()
        # target.md doesn't exist, so should be reported
        assert len(items) == 1
        assert "target" in items[0].title

    def test_existing_target_with_alias_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\n---\n[[b|Display text]]",
                "wiki/b.md": "---\ntitle: B\n---\nHello",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_missing_pages()
        assert items == []

    def test_stable_id_for_same_target(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "---\ntitle: A\n---\n[[missing]]"},
        )
        r1 = WikiReview(tmp_path).check_missing_pages()
        r2 = WikiReview(tmp_path).check_missing_pages()
        assert r1[0].id == r2[0].id


# ============================================================================
# Duplicates
# ============================================================================


class TestCheckDuplicates:
    def test_no_wiki_dir(self, tmp_path: Path) -> None:
        reviewer = WikiReview(tmp_path)
        assert reviewer.check_duplicates() == []

    def test_distinct_titles_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: Alpha\n---\nbody",
                "wiki/b.md": "---\ntitle: Beta\n---\nbody",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_duplicates()
        assert items == []

    def test_similar_titles_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: Deep Transformer Model Architecture\n---\nbody",
                "wiki/b.md": "---\ntitle: Deep Transformer Model Implementation\n---\nbody",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_duplicates()
        assert len(items) == 1
        assert items[0].type == ReviewType.DUPLICATE
        assert "Deep" in items[0].title

    def test_single_token_titles_not_reported(self, tmp_path: Path) -> None:
        """两个单字标题不应被判为重复(规模检查)"""
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: Foo\n---\nbody",
                "wiki/b.md": "---\ntitle: Foo\n---\nbody",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_duplicates()
        assert items == []

    def test_pair_reported_once(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: Deep Transformer Model Architecture\n---\nbody",
                "wiki/b.md": "---\ntitle: Deep Transformer Model Implementation\n---\nbody",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_duplicates()
        assert len(items) == 1  # 不重复报告


# ============================================================================
# Contradictions
# ============================================================================


class TestCheckContradictions:
    def test_no_wiki_dir(self, tmp_path: Path) -> None:
        reviewer = WikiReview(tmp_path)
        assert reviewer.check_contradictions() == []

    def test_consistent_dates_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\ncreated: 2026-01-01\nupdated: 2026-09-06\n---\nbody",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_contradictions()
        assert items == []

    def test_inconsistent_dates_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\ncreated: 2026-09-06\nupdated: 2026-01-01\n---\nbody",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_contradictions()
        assert len(items) == 1
        assert items[0].type == ReviewType.CONTRADICTION
        assert items[0].confidence == 1.0

    def test_missing_dates_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "---\ntitle: A\n---\nbody"},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_contradictions()
        assert items == []


# ============================================================================
# Suggestions
# ============================================================================


class TestCheckSuggestions:
    def test_no_wiki_dir(self, tmp_path: Path) -> None:
        reviewer = WikiReview(tmp_path)
        assert reviewer.check_suggestions() == []

    def test_long_page_with_title_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\n---\n" + ("long content " * 100),
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_suggestions()
        assert items == []

    def test_short_page_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "---\ntitle: A\n---\nshort"},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_suggestions()
        # Should have at least one SUGGESTION for short page
        short_items = [i for i in items if i.detail == "short_page"]
        assert len(short_items) == 1
        assert short_items[0].confidence == 0.6

    def test_missing_title_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "---\ncreated: 2026-09-06\n---\n" + ("long " * 100)},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_suggestions()
        title_items = [i for i in items if i.detail == "missing_title"]
        assert len(title_items) == 1
        assert title_items[0].confidence == 0.9

    def test_no_frontmatter_reports_missing_title(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/a.md": "just raw content, no frontmatter at all, " * 20},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_suggestions()
        title_items = [i for i in items if i.detail == "missing_title"]
        assert len(title_items) == 1


# ============================================================================
# Confirm (orphan / zero incoming)
# ============================================================================


class TestCheckConfirm:
    def test_no_wiki_dir(self, tmp_path: Path) -> None:
        reviewer = WikiReview(tmp_path)
        assert reviewer.check_confirm() == []

    def test_referenced_page_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\n---\nSee [[b]]",
                "wiki/b.md": "---\ntitle: B\n---\nHello",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_confirm()
        orphans = [i for i in items if i.detail == "zero_incoming"]
        # b 被 a 引用; a 没被引用 -> a 应该被报
        orphan_pages = [i.affected_pages[0] for i in orphans]
        assert "wiki/a.md" in orphan_pages
        assert "wiki/b.md" not in orphan_pages

    def test_exempt_pages_not_reported(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/schema.md": "---\ntitle: Schema\n---\nNo one links here",
                "wiki/overview.md": "---\ntitle: Overview\n---\nNo one links here",
            },
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_confirm()
        orphans = [i for i in items if i.detail == "zero_incoming"]
        assert orphans == []

    def test_orphan_has_0_5_confidence(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {"wiki/lonely.md": "---\ntitle: Lonely\n---\nNo one links here"},
        )
        reviewer = WikiReview(tmp_path)
        items = reviewer.check_confirm()
        assert len(items) == 1
        assert items[0].confidence == 0.5
        assert items[0].type == ReviewType.CONFIRM


# ============================================================================
# check_all
# ============================================================================


class TestCheckAll:
    def test_check_all_combines_everything(self, tmp_path: Path) -> None:
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: A\n---\nSee [[missing]]",
                "wiki/orphan.md": "---\ntitle: Orphan\n---\nshort",
            },
        )
        reviewer = WikiReview(tmp_path)
        result = reviewer.check_all()
        assert isinstance(result, ReviewResult)
        assert result.total > 0
        types = {i.type for i in result.items}
        # Should have at least missing-page (from broken link) and suggestion (short page)
        assert ReviewType.MISSING_PAGE in types
        assert ReviewType.SUGGESTION in types

    def test_check_all_clean_project(self, tmp_path: Path) -> None:
        """一个结构良好、互相引用的 wiki 应只有少量或零项"""
        _make_project(
            tmp_path,
            {
                "wiki/a.md": "---\ntitle: Alpha\n---\nLong body. " * 30 + "\nSee [[b]]",
                "wiki/b.md": "---\ntitle: Beta\n---\nLong body. " * 30 + "\nSee [[a]]",
            },
        )
        reviewer = WikiReview(tmp_path)
        result = reviewer.check_all()
        # 无 missing / no contradiction / no duplicate / no confirm (both referenced)
        missing = [i for i in result.items if i.type == ReviewType.MISSING_PAGE]
        contradictions = [i for i in result.items if i.type == ReviewType.CONTRADICTION]
        duplicates = [i for i in result.items if i.type == ReviewType.DUPLICATE]
        confirms = [i for i in result.items if i.type == ReviewType.CONFIRM]
        assert missing == []
        assert contradictions == []
        assert duplicates == []
        assert confirms == []


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    def test_non_utf8_file_does_not_crash(self, tmp_path: Path) -> None:
        # 写入无效 UTF-8 字节
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        bad = wiki_dir / "bad.md"
        bad.write_bytes(b"---\ntitle: X\n---\n\xff\xfe invalid")
        reviewer = WikiReview(tmp_path)
        # 不应该抛 UnicodeDecodeError
        result = reviewer.check_all()
        assert isinstance(result, ReviewResult)

    def test_empty_wiki_dir(self, tmp_path: Path) -> None:
        (tmp_path / "wiki").mkdir()
        reviewer = WikiReview(tmp_path)
        result = reviewer.check_all()
        assert result.total == 0

    def test_review_type_enum_values(self) -> None:
        assert ReviewType.MISSING_PAGE.value == "missing-page"
        assert ReviewType.DUPLICATE.value == "duplicate"
        assert ReviewType.CONTRADICTION.value == "contradiction"
        assert ReviewType.CONFIRM.value == "confirm"
        assert ReviewType.SUGGESTION.value == "suggestion"

    @pytest.mark.parametrize(
        "type_",
        list(ReviewType),
    )
    def test_stable_id_roundtrip_for_each_type(self, type_: ReviewType) -> None:
        id1 = _stable_id(type_, "a", "b")
        id2 = _stable_id(type_, "a", "b")
        assert id1 == id2
        assert id1.startswith("rv-")
