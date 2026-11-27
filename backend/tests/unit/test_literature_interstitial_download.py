"""文献下载中间页（``pdf.interstitial``）路径单元测试。

覆盖 `download_pdf` 的「入口 href → 新标签 → 等跳转 → 主机回退 → 验证」
路径，以及 `SageToolDriver` 的 attr / 标签页能力。
"""

from __future__ import annotations

import pytest

from backend.tests.unit.test_literature_pipeline import (
    _FakeCall,
    _FakeDriver,
    _raw_profile,
)

pytestmark = pytest.mark.unit


class _InterstitialDriver(_FakeDriver):
    """模拟中间页站点：入口 href → 新标签 → 跳转后按回退主机导航下载。"""

    def __init__(self):
        super().__init__()
        self.attrs = []
        self.opened = []
        self.focused = []
        self.closed = []
        self.tab_sleeps = []
        self.navigations = []
        self.entry_href = "https://www.xueshu789.cc/doDownload?url=x&ddata=y"
        self.tabs_state = [
            {
                "tab_id": "t1",
                "url": "https://oversea.cnki.net/docdown/fulltext/download?q=abc",
                "active": True,
            }
        ]
        self.navigate_errors = {}

    def element_attr(self, selector, name="href"):
        self.attrs.append((selector, name))
        return self.entry_href

    def open_tab(self, url):
        self.opened.append(url)
        return "t1"

    def sleep(self, seconds):
        self.tab_sleeps.append(seconds)

    def tabs(self):
        return self.tabs_state

    def focus_tab(self, tab_id):
        self.focused.append(tab_id)

    def close_tab(self, tab_id):
        self.closed.append(tab_id)

    def navigate(self, url, wait_for=""):
        self.navigations.append(url)
        if url in self.navigate_errors:
            raise RuntimeError(self.navigate_errors[url])
        return url


def _interstitial_profile(**overrides):
    from backend.literature.models import profile_from_dict

    raw = _raw_profile()
    interstitial = {
        "url_contains": ["cnki.net/docdown"],
        "host_fallbacks": ["kns.cnki.net"],
    }
    interstitial.update(overrides)
    raw["pdf"]["interstitial"] = interstitial
    return profile_from_dict(raw)


class TestInterstitialDownload:
    def test_download_interstitial_rewrites_host_and_validates(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.6\nfake")
        driver.download_path = str(pdf)
        result = download_pdf(
            _interstitial_profile(),
            driver,
            "示例论文",
            tmp_path,
            entry_selector="table tbody tr:nth-child(1) a.downloadlink",
        )
        assert result.ok is True, result.errors
        assert driver.attrs == [("table tbody tr:nth-child(1) a.downloadlink", "href")]
        assert driver.opened == ["https://www.xueshu789.cc/doDownload?url=x&ddata=y"]
        assert driver.focused == ["t1"]
        assert driver.navigations[0].startswith("https://kns.cnki.net/docdown/")
        assert "q=abc" in driver.navigations[0]
        assert driver.closed == ["t1"]
        assert driver.clicks == []

    def test_download_interstitial_tolerates_navigation_abort(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.6\nfake")
        driver.download_path = str(pdf)
        kns_url = "https://kns.cnki.net/docdown/fulltext/download?q=abc"
        driver.navigate_errors[kns_url] = "net::ERR_ABORTED"
        result = download_pdf(_interstitial_profile(), driver, "示例论文", tmp_path)
        assert result.ok is True, result.errors

    def test_download_interstitial_without_tab_fails(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        driver.tabs_state = []
        result = download_pdf(
            _interstitial_profile(tab_timeout_s=0),
            driver,
            "示例论文",
            tmp_path,
        )
        assert result.ok is False
        assert any("url_contains" in e for e in result.errors)

    def test_download_interstitial_falls_back_to_click_without_capabilities(
        self, tmp_path
    ):
        from backend.literature.search import download_pdf

        driver = _FakeDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.6\nfake")
        driver.download_path = str(pdf)
        result = download_pdf(_interstitial_profile(), driver, "示例论文", tmp_path)
        assert result.ok is True, result.errors
        assert driver.clicks == ["a.downloadlink"]

    def test_candidate_urls_order(self):
        from backend.literature.search import _candidate_download_urls

        urls = _candidate_download_urls(
            "https://oversea.cnki.net/docdown/x?q=1&invoice=2",
            ["kns.cnki.net", "kns.cnki.net", "alt.example"],
        )
        assert urls[0] == "https://kns.cnki.net/docdown/x?q=1&invoice=2"
        assert urls[1] == "https://alt.example/docdown/x?q=1&invoice=2"
        assert urls[2].startswith("https://oversea.cnki.net/docdown/x?q=1")
        assert len(urls) == 3


class TestDriverInterstitialCapabilities:
    def test_element_attr_reads_info(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_interact"] = {
            "action": "attr",
            "info": "https://www.xueshu789.cc/doDownload?url=x&ddata=y",
        }
        driver = SageToolDriver(call)
        value = driver.element_attr("table tbody tr a.downloadlink")
        assert value.startswith("https://www.xueshu789.cc/doDownload")
        assert call.calls[-1] == (
            "browser_interact",
            {
                "action": "attr",
                "selector": "table tbody tr a.downloadlink",
                "attr_name": "href",
            },
        )

    def test_tabs_lists_dicts(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_tabs"] = {
            "tabs": [
                {
                    "tab_id": "t1",
                    "url": "https://oversea.cnki.net/docdown?q=1",
                    "active": True,
                },
                "bad-entry",
            ]
        }
        driver = SageToolDriver(call)
        tabs = driver.tabs()
        assert tabs == [
            {
                "tab_id": "t1",
                "url": "https://oversea.cnki.net/docdown?q=1",
                "active": True,
            }
        ]

    def test_open_focus_close_tab(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_tabs"] = {"tab_id": "t9"}
        driver = SageToolDriver(call)
        assert driver.open_tab("https://a/do") == "t9"
        assert call.calls[-1] == (
            "browser_tabs",
            {"action": "create", "url": "https://a/do"},
        )
        driver.focus_tab("t9")
        assert call.calls[-1] == ("browser_tabs", {"action": "switch", "tab_id": "t9"})
        driver.close_tab("t9")
        assert call.calls[-1] == ("browser_tabs", {"action": "close", "tab_id": "t9"})
