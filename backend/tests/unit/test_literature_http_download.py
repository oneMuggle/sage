"""HTTP 下载快路径（spec §5.1 / §5.6）。"""

from pathlib import Path

import pytest

from backend.literature.http_download import (
    FetchResult,
    download_pdf_http,
)
from backend.literature.models import SiteProfile

pytestmark = pytest.mark.unit


def _profile() -> SiteProfile:
    return SiteProfile(
        id="demo",
        display_name="演示站",
        home_url="https://demo.example",
        domains=("demo.example",),
    )


_INTERSTITIAL_HTML = """
<html><script>
var downurl = "https://oversea.example.net/docdown/fulltext/download?q=abc&invoice=xyz";
</script></html>
"""


def _make_fetcher(body=b"%PDF-1.6 hello", interstitial=_INTERSTITIAL_HTML, status=200):
    calls = []

    def fetch(url, referer=""):
        calls.append((url, referer))
        if "docdown" in url and "interstitial" not in url and url.endswith("invoice=xyz"):
            # 这是最终 PDF 地址
            return FetchResult(status=status, body=body)
        return FetchResult(status=200, body=interstitial.encode("utf-8"))

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def test_download_pdf_http_writes_the_pdf(tmp_path: Path) -> None:
    fetch = _make_fetcher()
    outcome = download_pdf_http(
        _profile(),
        "https://demo.example/doDownload?x=1",
        "演示题名",
        tmp_path,
        fetch,
    )
    assert outcome.ok is True, outcome.errors
    assert outcome.transport == "http"
    assert outcome.path
    assert Path(outcome.path).read_bytes().startswith(b"%PDF-")


def test_download_pdf_http_without_entry_url_reports_reason(tmp_path: Path) -> None:
    outcome = download_pdf_http(_profile(), "", "题名", tmp_path, _make_fetcher())
    assert outcome.ok is False
    assert outcome.fallback_reason == "no_entry_url"


def test_download_pdf_http_reports_entry_fetch_failure(tmp_path: Path) -> None:
    def failing_fetch(url, referer=""):
        return FetchResult(status=500, body=b"boom")

    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, failing_fetch
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "entry_status_500"


def test_download_pdf_http_reports_parse_miss(tmp_path: Path) -> None:
    def plain_fetch(url, referer=""):
        return FetchResult(status=200, body=b"<html>no link</html>")

    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, plain_fetch
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "interstitial_parse_miss"


def test_download_pdf_http_reports_candidate_exhausted(tmp_path: Path) -> None:
    """候选地址全部取不到（网络层失败）→ candidate_exhausted。

    注意与下面的 ``magic_mismatch`` 用例区分：那个是「取到了但不是 PDF」。
    """

    def dead_candidates(url, referer=""):
        if "docdown" in url:
            return FetchResult(status=404, body=b"")
        return FetchResult(status=200, body=_INTERSTITIAL_HTML.encode("utf-8"))

    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, dead_candidates
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "candidate_exhausted"


def test_download_pdf_http_rejects_non_pdf_body(tmp_path: Path) -> None:
    """候选地址取到了响应但不是 PDF（登录墙 / 错误页）→ magic_mismatch。"""
    fetch = _make_fetcher(body=b"<html>login wall</html>")
    outcome = download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, fetch
    )
    assert outcome.ok is False
    assert outcome.fallback_reason == "magic_mismatch"
    assert not list(tmp_path.glob("*.pdf"))


def test_download_pdf_http_leaves_no_partial_file(tmp_path: Path) -> None:
    fetch = _make_fetcher(body=b"<html>not pdf</html>")
    download_pdf_http(
        _profile(), "https://demo.example/doDownload", "题名", tmp_path, fetch
    )
    assert not list(tmp_path.glob("*.part"))
