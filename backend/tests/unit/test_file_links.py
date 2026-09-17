# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""file_links 候选文件链接嗅探单测（Round 5 B4 / SN2）。"""

import pytest

from backend.tools.file_links import (
    classify_mime,
    classify_url,
    extract_file_links,
    merge_file_links,
)

pytestmark = [pytest.mark.unit]

_BASE = "https://journal.example.org/article/123"


def _urls(items):
    return [i["url"] for i in items]


def test_citation_pdf_url_ranks_first():
    html = """
    <html><head>
      <meta name="citation_title" content="A paper">
      <meta name="citation_pdf_url" content="https://journal.example.org/content/123.pdf">
    </head><body>
      <a href="/article/123/related">Related articles</a>
      <a href="/article/123/download">Download PDF</a>
    </body></html>
    """
    items = extract_file_links(html, _BASE)
    assert items[0]["url"] == "https://journal.example.org/content/123.pdf"
    assert items[0]["kind"] == "pdf"
    assert "meta:citation_pdf_url" in items[0]["sources"]
    assert "https://journal.example.org/article/123/download" in _urls(items)
    assert "https://journal.example.org/article/123/related" not in _urls(items)


def test_anchor_download_attribute_and_extension():
    html = """
    <a href="report.docx" download="Q3.docx">季度报告</a>
    <a href="/files/data.zip">data</a>
    <a href="/about">About us</a>
    <a href="mailto:x@y.z">mail</a>
    """
    items = extract_file_links(html, "https://site.example/dir/")
    by_url = {i["url"]: i for i in items}
    docx = by_url["https://site.example/dir/report.docx"]
    assert docx["ext"] == "docx"
    assert docx["kind"] == "office"
    assert docx["download_name"] == "Q3.docx"
    assert "anchor:download" in docx["sources"]
    assert by_url["https://site.example/files/data.zip"]["kind"] == "archive"
    assert "https://site.example/about" not in by_url
    assert docx["score"] > by_url["https://site.example/files/data.zip"]["score"]


def test_iframe_embed_and_meta_refresh():
    html = """
    <meta http-equiv="refresh" content="0; url=/redirect/paper.pdf">
    <iframe src="/viewer/embed.pdf"></iframe>
    <embed type="application/pdf" src="/stream/doc?id=1">
    <object data="/o/manual.pdf"></object>
    <iframe src="https://www.youtube.com/embed/xyz"></iframe>
    """
    items = extract_file_links(html, "https://site.example/")
    urls = _urls(items)
    assert "https://site.example/redirect/paper.pdf" in urls
    assert "https://site.example/viewer/embed.pdf" in urls
    assert "https://site.example/stream/doc?id=1" in urls  # type=application/pdf 无后缀
    assert "https://site.example/o/manual.pdf" in urls
    assert "https://www.youtube.com/embed/xyz" not in urls


def test_link_alternate_pdf():
    html = '<link rel="alternate" type="application/pdf" href="/alt.pdf" title="PDF"><link rel="stylesheet" href="/a.css">'
    items = extract_file_links(html, "https://site.example/")
    assert _urls(items) == ["https://site.example/alt.pdf"]
    assert items[0]["mime"] == "application/pdf"


def test_hint_text_without_extension_is_low_score_but_kept():
    html = '<a href="/get?id=9">点击下载全文</a><a href="/get?id=10">评论</a>'
    items = extract_file_links(html, "https://site.example/")
    assert _urls(items) == ["https://site.example/get?id=9"]
    assert items[0]["kind"] is None
    assert items[0]["score"] >= 25


def test_dedup_merges_sources_and_keeps_best_score():
    html = """
    <meta name="citation_pdf_url" content="/p.pdf">
    <a href="/p.pdf#page=2">PDF</a>
    <a href="/p.pdf">Full text</a>
    """
    items = extract_file_links(html, "https://site.example/")
    assert len(items) == 1
    assert items[0]["url"] == "https://site.example/p.pdf"
    assert set(items[0]["sources"]) == {"meta:citation_pdf_url", "anchor"}


def test_negative_urls_are_penalized():
    html = '<a href="/login?next=/x.pdf">登录下载 PDF</a><a href="/x.pdf">PDF</a>'
    items = extract_file_links(html, "https://site.example/")
    assert items[0]["url"] == "https://site.example/x.pdf"


def test_limit_and_malformed_html():
    html = "".join(f'<a href="/f{i}.pdf">f{i}' for i in range(80)) + "<div><a href='/broken.pdf"
    items = extract_file_links(html, "https://site.example/", limit=10)
    assert len(items) == 10


@pytest.mark.parametrize(
    ("url", "ext", "kind"),
    [
        ("https://a/b/c.PDF?x=1", "pdf", "pdf"),
        ("https://a/b/c.tar.gz", "gz", "archive"),
        ("https://a/b/c.xlsx", "xlsx", "office"),
        ("https://a/b/c", None, None),
        ("https://a/b/c.html", None, None),
    ],
)
def test_classify_url(url, ext, kind):
    assert classify_url(url) == (ext, kind)


def test_classify_mime():
    assert classify_mime("application/pdf; charset=binary") == "pdf"
    assert (
        classify_mime("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        == "office"
    )
    assert classify_mime("text/html") is None
    assert classify_mime("") is None


def test_merge_file_links_prefers_higher_score():
    a = [{"url": "https://s/x.pdf", "score": 50, "sources": ["anchor"], "kind": "pdf"}]
    b = [
        {
            "url": "https://s/x.pdf",
            "score": 90,
            "sources": ["meta:citation_pdf_url"],
            "kind": "pdf",
        },
        {"url": "https://s/y.zip", "score": 40, "sources": ["anchor"], "kind": "archive"},
    ]
    merged = merge_file_links(a, b)
    assert [m["url"] for m in merged] == ["https://s/x.pdf", "https://s/y.zip"]
    assert merged[0]["score"] == 90
    assert merged[0]["sources"] == ["anchor", "meta:citation_pdf_url"]
