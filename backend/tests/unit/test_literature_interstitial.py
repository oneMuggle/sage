"""中间页解析与主机回退（spec §5.3）。"""

import pytest

from backend.literature.interstitial import (
    parse_download_url,
    rewrite_host_candidates,
    select_first_valid,
)

pytestmark = pytest.mark.unit

_HTML_VAR = """
<html><body><script>
var downurl = "https://oversea.cnki.net/docdown/fulltext/download?q=abc&invoice=xyz";
</script></body></html>
"""
_HTML_LOCATION = """
<html><body><script>
window.location = "https://example.org/download?token=1";
</script></body></html>
"""
_HTML_ANCHOR = """
<html><body><a id="successBtn" href="https://example.net/dl?x=2">下载</a></body></html>
"""
_HTML_HREF_FIRST = """
<html><body><a href="https://example.org/a" id="successBtn">下载</a></body></html>
"""


def test_parse_var_downurl() -> None:
    assert parse_download_url(_HTML_VAR) == [
        "https://oversea.cnki.net/docdown/fulltext/download?q=abc&invoice=xyz"
    ]


def test_parse_window_location() -> None:
    assert parse_download_url(_HTML_LOCATION) == [
        "https://example.org/download?token=1"
    ]


def test_parse_anchor_href() -> None:
    assert parse_download_url(_HTML_ANCHOR) == ["https://example.net/dl?x=2"]


def test_parse_anchor_href_before_id() -> None:
    """属性顺序不限。"""
    assert parse_download_url(_HTML_HREF_FIRST) == ["https://example.org/a"]


def test_parse_returns_all_candidates_in_order_without_duplicates() -> None:
    html = _HTML_VAR + _HTML_LOCATION
    urls = parse_download_url(html)
    assert len(urls) == 2
    assert urls[0].startswith("https://oversea.cnki.net")
    assert urls[1].startswith("https://example.org")


def test_parse_deduplicates_repeated_urls() -> None:
    html = _HTML_VAR + _HTML_VAR
    assert len(parse_download_url(html)) == 1


def test_parse_misses_return_empty_list() -> None:
    assert parse_download_url("<html><body>无下载链接</body></html>") == []


def test_rewrite_host_candidates_puts_fallbacks_before_original() -> None:
    url = "https://oversea.cnki.net/docdown/fulltext/download?q=abc"
    candidates = rewrite_host_candidates(url, ["kns.cnki.net"])
    assert candidates[0] == "https://kns.cnki.net/docdown/fulltext/download?q=abc"
    assert candidates[-1] == url


def test_rewrite_host_candidates_keeps_path_and_query() -> None:
    url = "https://oversea.cnki.net/docdown/fulltext/download?q=abc&invoice=xyz"
    candidates = rewrite_host_candidates(url, ["kns.cnki.net"])
    assert candidates[0].endswith("?q=abc&invoice=xyz")
    assert "/docdown/fulltext/download" in candidates[0]


def test_rewrite_host_candidates_with_no_fallbacks_returns_original() -> None:
    url = "https://example.org/a?b=1"
    assert rewrite_host_candidates(url, []) == [url]


def test_rewrite_host_candidates_skips_blank_hosts() -> None:
    """空主机必须跳过 —— 否则会产出 ``https:///path`` 这种坏候选。"""
    url = "https://example.org/a?b=1"
    candidates = rewrite_host_candidates(url, ["", "   ", "alt.example"])
    assert candidates == ["https://alt.example/a?b=1", url]


def test_select_first_valid_skips_failing_candidate() -> None:
    calls = []

    def fake_fetch(url):
        calls.append(url)
        if url.startswith("https://oversea.cnki.net"):
            return url, b"%PDF-1.6 body"
        return None

    candidates = rewrite_host_candidates(
        "https://oversea.cnki.net/docdown/fulltext/download?q=abc", ["kns.cnki.net"]
    )
    result = select_first_valid(candidates, fake_fetch)
    assert result is not None
    url, body = result
    assert url.startswith("https://oversea.cnki.net")
    assert body.startswith(b"%PDF-")
    assert len(calls) == 2


def test_select_first_valid_applies_validator() -> None:
    def fake_fetch(url):
        return url, b"<html>not a pdf</html>"

    result = select_first_valid(
        ["https://example.org/a"], fake_fetch, lambda b: b.startswith(b"%PDF-")
    )
    assert result is None


def test_select_first_valid_returns_none_when_all_fail() -> None:
    assert select_first_valid(["https://example.org/a"], lambda url: None) is None
