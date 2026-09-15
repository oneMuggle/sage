"""Unit tests for the citation engine (Round 9): GB/T 7714 / APA / BibTeX.

Covers :mod:`backend.office.references` formatters and
:mod:`backend.office.bibtex` parser — pure functions, no docx / no I/O.
"""

from __future__ import annotations

import pytest

from backend.office.bibtex import parse_bibtex
from backend.office.errors import OfficeParseError
from backend.office.models import ReferenceSpec
from backend.office.references import (
    compact_citation_marker,
    format_apa,
    format_authors,
    format_gbt7714,
)


def _ref(**overrides) -> ReferenceSpec:
    base: dict = {
        "key": "k",
        "ref_type": "journal",
        "title": "量子计算综述",
        "authors": ["李四", "王五"],
        "year": "2023",
        "source": "计算机学报",
        "volume": "46",
        "issue": "5",
        "pages": "100-110",
    }
    base.update(overrides)
    return ReferenceSpec(**base)


# ──────────────────────────────────────────────────────────────────────
# GB/T 7714-2015
# ──────────────────────────────────────────────────────────────────────


def test_gbt_journal_full() -> None:
    text = format_gbt7714(_ref())
    assert text == "李四, 王五. 量子计算综述[J]. 计算机学报, 2023, 46(5): 100-110."


def test_gbt_journal_more_than_three_authors_truncates() -> None:
    text = format_gbt7714(_ref(authors=["李四", "王五", "张三", "赵六"]))
    assert text.startswith("李四, 王五, 张三 等. ")


def test_gbt_english_authors_use_et_al() -> None:
    text = format_gbt7714(
        _ref(
            title="Deep Learning",
            authors=["Goodfellow I", "Bengio Y", "Courville A", "Others X"],
            language="en",
        )
    )
    assert text.startswith("Goodfellow I, Bengio Y, Courville A et al. ")


def test_gbt_language_defaults_to_cjk_detection() -> None:
    # title 含 CJK → "等"；纯 ASCII → "et al"
    assert "等." in format_gbt7714(_ref(authors=["甲", "乙", "丙", "丁"]))
    assert (
        "et al." in format_gbt7714(
            _ref(title="Alignment Survey", authors=["A B", "C D", "E F", "G H"], language="en")
        )
    )


def test_gbt_book() -> None:
    text = format_gbt7714(
        _ref(ref_type="book", source=None, volume=None, issue=None, pages=None,
             address="北京", publisher="清华大学出版社")
    )
    assert text == "李四, 王五. 量子计算综述[M]. 北京: 清华大学出版社, 2023."


def test_gbt_thesis() -> None:
    text = format_gbt7714(
        _ref(ref_type="thesis", source="清华大学", volume=None, issue=None,
             pages=None, address="北京")
    )
    assert text == "李四, 王五. 量子计算综述[D]. 北京: 清华大学, 2023."


def test_gbt_conference_uses_double_slash() -> None:
    text = format_gbt7714(
        _ref(ref_type="conference", source="全国计算数学年会", volume=None,
             issue=None, address="西安", publisher="科学出版社")
    )
    assert "[C]// 全国计算数学年会." in text
    assert "西安: 科学出版社, 2023: 100-110." in text


def test_gbt_webpage_with_url_and_access_date() -> None:
    text = format_gbt7714(
        _ref(ref_type="webpage", source=None, volume=None, issue=None,
             pages=None, year=None, url="https://example.com", access_date="2026-09-11")
    )
    assert text == "李四, 王五. 量子计算综述[EB/OL]. [2026-09-11]. https://example.com."


def test_gbt_webpage_doi_fallback() -> None:
    text = format_gbt7714(
        _ref(ref_type="webpage", source=None, volume=None, issue=None,
             pages=None, year=None, doi="10.1234/abc")
    )
    assert text.endswith("DOI: 10.1234/abc.")


def test_gbt_minimal_fields_still_well_formed() -> None:
    text = format_gbt7714(_ref(source=None, volume=None, issue=None, pages=None))
    assert text == "李四, 王五. 量子计算综述[J]. 2023."


# ──────────────────────────────────────────────────────────────────────
# APA (simplified subset)
# ──────────────────────────────────────────────────────────────────────


def test_apa_journal_with_doi() -> None:
    text = format_apa(_ref(doi="10.1234/x", language="en",
                           title="Quantum Survey",
                           authors=["Zhang S", "Wang W"]))
    assert text == "Zhang S, Wang W (2023). Quantum Survey. 计算机学报, 46(5), 100-110. https://doi.org/10.1234/x"


def test_apa_book_publisher() -> None:
    text = format_apa(
        _ref(ref_type="book", source=None, volume=None, issue=None, pages=None,
             publisher="MIT Press", language="en", title="Deep Learning",
             authors=["Goodfellow I"])
    )
    assert text == "Goodfellow I (2023). Deep Learning. MIT Press."


def test_format_authors_empty() -> None:
    assert format_authors(_ref(authors=[]), style="gbt7714") == ""


# ──────────────────────────────────────────────────────────────────────
# Compact citation marker
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ([1], "[1]"),
        ([2, 1], "[1-2]"),
        ([3, 1, 2, 5], "[1-3,5]"),
        ([5, 6, 7, 10], "[5-7,10]"),
        ([], ""),
    ],
)
def test_compact_citation_marker(numbers: list, expected: str) -> None:
    assert compact_citation_marker(numbers) == expected


# ──────────────────────────────────────────────────────────────────────
# BibTeX parser
# ──────────────────────────────────────────────────────────────────────

_SAMPLE_BIB = """
@article{zhang2023,
  author = {李四 and 王五 and 张三 and 赵六},
  title = {量子计算{综述}},
  journal = {计算机学报},
  year = {2023},
  volume = {46},
  number = {5},
  pages = {100--110}
}

@inproceedings{li2016deep,
  author = "Li, Y. and Wu, X.",
  title = "Deep Learning",
  booktitle = {ICML},
  year = 2016,
  publisher = {ACM}
}

@misc{sage2026,
  author = {Sage Team},
  title = {Sage Docs},
  url = {https://example.com},
  year = {2026}
}

@phdthesis{wang2020thesis,
  author = {孙七},
  title = {分布式系统研究},
  school = {清华大学},
  year = {2020}
}
"""


def test_parse_bibtex_entry_types() -> None:
    specs = parse_bibtex(_SAMPLE_BIB)
    assert [s.ref_type for s in specs] == ["journal", "conference", "webpage", "thesis"]


def test_parse_bibtex_field_cleanup() -> None:
    spec = parse_bibtex(_SAMPLE_BIB)[0]
    # 内层花括号剥除、-- → -、author and 切分
    assert spec.title == "量子计算综述"
    assert spec.pages == "100-110"
    assert spec.authors == ["李四", "王五", "张三", "赵六"]
    assert spec.issue == "5"


def test_parse_bibtex_key_and_number_as_year() -> None:
    specs = parse_bibtex(_SAMPLE_BIB)
    assert specs[1].key == "li2016deep"
    assert specs[1].year == "2016"  # 裸数字值
    assert specs[1].source == "ICML"  # booktitle → source


def test_parse_bibtex_misc_without_url_becomes_report() -> None:
    specs = parse_bibtex("@misc{x1, title={Note}, note={draft}}")
    assert specs[0].ref_type == "report"


def test_parse_bibtex_bad_entry_skipped_good_kept() -> None:
    text = _SAMPLE_BIB + "\n@article{broken, title = {未闭合"
    specs = parse_bibtex(text)
    assert {s.key for s in specs} == {"zhang2023", "li2016deep", "sage2026", "wang2020thesis"}


def test_parse_bibtex_empty_raises() -> None:
    with pytest.raises(OfficeParseError):
        parse_bibtex("   ")


def test_parse_bibtex_no_entries_raises() -> None:
    with pytest.raises(OfficeParseError):
        parse_bibtex("这不是 BibTeX 内容")
