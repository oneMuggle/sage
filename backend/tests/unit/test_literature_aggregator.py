"""文献综述聚合单元测试 (2026-09-25)

项目类型分类系统 - Phase 9.5.3
"""

from __future__ import annotations

from pathlib import Path

from backend.wiki.literature_aggregator import (
    extract_literature_entry,
    generate_literature_review,
    scan_literature_directory,
)


class TestExtractLiteratureEntry:
    """extract_literature_entry 测试"""

    def test_extracts_yaml_front_matter(self, tmp_path: Path) -> None:
        md_file = tmp_path / "paper.md"
        md_file.write_text(
            "---\n"
            "title: Attention Is All You Need\n"
            "authors: [Vaswani, Shazeer, Parmar]\n"
            "year: 2017\n"
            "tags: [transformer, nlp]\n"
            "---\n\n"
            "# Attention Is All You Need\n\n"
            "The dominant sequence transduction models...",
            encoding="utf-8",
        )

        entry = extract_literature_entry(md_file)
        assert entry is not None
        assert entry.title == "Attention Is All You Need"
        assert len(entry.authors) == 3
        assert entry.year == 2017
        assert "transformer" in entry.tags
        assert "dominant" in entry.summary

    def test_extracts_title_from_h1(self, tmp_path: Path) -> None:
        md_file = tmp_path / "simple.md"
        md_file.write_text(
            "# Deep Learning Survey\n\n"
            "This paper reviews deep learning methods from 2020.",
            encoding="utf-8",
        )

        entry = extract_literature_entry(md_file)
        assert entry is not None
        assert entry.title == "Deep Learning Survey"
        assert entry.year == 2020  # extracted from content
        assert entry.authors == []

    def test_fallback_to_filename(self, tmp_path: Path) -> None:
        md_file = tmp_path / "my-cool-paper.md"
        md_file.write_text("Some content without title.", encoding="utf-8")

        entry = extract_literature_entry(md_file)
        assert entry is not None
        assert entry.title == "My Cool Paper"

    def test_returns_none_for_empty_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "empty.md"
        md_file.write_text("", encoding="utf-8")

        entry = extract_literature_entry(md_file)
        assert entry is None

    def test_parses_quoted_authors(self, tmp_path: Path) -> None:
        md_file = tmp_path / "quoted.md"
        md_file.write_text(
            "---\n"
            'title: "Test Paper"\n'
            'authors: "Alice, Bob"\n'
            "year: 2023\n"
            "---\n\n"
            "Content here.",
            encoding="utf-8",
        )

        entry = extract_literature_entry(md_file)
        assert entry is not None
        assert "Alice" in entry.authors
        assert "Bob" in entry.authors


class TestScanLiteratureDirectory:
    """scan_literature_directory 测试"""

    def test_scans_markdown_files(self, tmp_path: Path) -> None:
        lit_dir = tmp_path / "wiki" / "literature"
        lit_dir.mkdir(parents=True)
        (lit_dir / "paper1.md").write_text("# Paper One\n2021", encoding="utf-8")
        (lit_dir / "paper2.md").write_text("# Paper Two\n2020", encoding="utf-8")

        entries = scan_literature_directory(tmp_path)
        assert len(entries) == 2
        # 按年份降序
        assert entries[0].year == 2021
        assert entries[1].year == 2020

    def test_returns_empty_for_missing_dir(self, tmp_path: Path) -> None:
        entries = scan_literature_directory(tmp_path)
        assert entries == []

    def test_sorts_no_year_last(self, tmp_path: Path) -> None:
        lit_dir = tmp_path / "wiki" / "literature"
        lit_dir.mkdir(parents=True)
        (lit_dir / "no-year.md").write_text("# No Year Paper", encoding="utf-8")
        (lit_dir / "with-year.md").write_text("# With Year\n2019", encoding="utf-8")

        entries = scan_literature_directory(tmp_path)
        assert len(entries) == 2
        assert entries[0].year == 2019
        assert entries[1].year is None


class TestGenerateLiteratureReview:
    """generate_literature_review 集成测试"""

    def test_generates_index_page(self, tmp_path: Path) -> None:
        lit_dir = tmp_path / "wiki" / "literature"
        lit_dir.mkdir(parents=True)
        (lit_dir / "paper1.md").write_text(
            "---\ntitle: Paper A\nyear: 2022\n---\n# Paper A\nSummary A",
            encoding="utf-8",
        )
        (lit_dir / "paper2.md").write_text(
            "---\ntitle: Paper B\nyear: 2021\n---\n# Paper B\nSummary B",
            encoding="utf-8",
        )

        result = generate_literature_review(tmp_path)
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "# 文献综述索引" in content
        assert "共 2 篇文献" in content
        assert "2022 年" in content
        assert "Paper A" in content

    def test_returns_none_when_no_entries(self, tmp_path: Path) -> None:
        result = generate_literature_review(tmp_path)
        assert result is None

    def test_groups_by_year(self, tmp_path: Path) -> None:
        lit_dir = tmp_path / "wiki" / "literature"
        lit_dir.mkdir(parents=True)
        (lit_dir / "old.md").write_text(
            "---\ntitle: Old Paper\nyear: 2018\n---\n# Old\nOld summary",
            encoding="utf-8",
        )
        (lit_dir / "new.md").write_text(
            "---\ntitle: New Paper\nyear: 2023\n---\n# New\nNew summary",
            encoding="utf-8",
        )
        (lit_dir / "no-year.md").write_text(
            "---\ntitle: Unknown Year\n---\n# Unknown\nNo year info",
            encoding="utf-8",
        )

        result = generate_literature_review(tmp_path)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "2023 年" in content
        assert "2018 年" in content
        assert "待分类" in content
