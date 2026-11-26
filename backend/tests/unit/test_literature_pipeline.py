"""文献调研最小闭环：模型 / 运行目录 / 门禁 / 导出 / 检索 / CLI。"""

from __future__ import annotations

import json

import pytest

from backend.literature.pipeline_models import (
    EvidenceRecord,
    GateReport,
    Outline,
    evidence_from_dict,
    outline_from_dict,
    paper_record_from_dict,
)

pytestmark = pytest.mark.unit


def _paper(key="p1", title="示例论文", authors=("张三",), year="2024"):
    return {
        "paper_key": key,
        "title": title,
        "authors": list(authors),
        "year": year,
        "venue": "示例期刊",
        "source_site": "demo",
    }


def _raw_profile(**overrides):
    raw = {
        "id": "demo",
        "display_name": "Demo 学术站",
        "home_url": "https://demo.example/",
        "domains": ["demo.example"],
        "access": {
            "mode": "browser",
            "login": {
                "method": "form",
                "account_label": "卡号",
                "password_label": "密码",
                "url_contains": "/home/",
                "title_not_contains": "登录",
            },
        },
        "capabilities": {"search": True, "pdf_download": True},
        "search": {
            "url_template": "https://demo.example/search?q={query}&n={limit}",
            "wait_for": [".result-list"],
            "result_fields": {"title": {"selector": ".title"}},
        },
        "pdf": {"entry": {"selector": "a.downloadlink"}, "forbid": ["CAJ"]},
        "compliance": {"note": "仅个人学习", "default_enabled": False},
    }
    raw.update(overrides)
    return raw


class TestPipelineModels:
    def test_paper_record_from_dict(self):
        record = paper_record_from_dict(_paper())
        assert record.paper_key == "p1"
        assert record.authors == ("张三",)
        with pytest.raises(ValueError, match="paper_key"):
            paper_record_from_dict({"title": "缺 key"})
        with pytest.raises(ValueError, match="title"):
            paper_record_from_dict({"paper_key": "p1", "title": " "})

    def test_evidence_from_dict_requires_paper_key(self):
        record = evidence_from_dict(
            {
                "evidence_id": "e1",
                "paper_key": "p1",
                "kind": "finding",
                "text": "发现 A",
                "locator": "p.3",
            }
        )
        assert record.kind == "finding"
        assert isinstance(record, EvidenceRecord)
        with pytest.raises(ValueError, match="paper_key"):
            evidence_from_dict({"evidence_id": "e1", "kind": "finding", "text": "x"})

    def test_outline_from_dict(self):
        outline = outline_from_dict(
            {
                "title": "综述",
                "sections": [
                    {"id": "s1", "title": "引言", "summary": "背景", "source_keys": ["p1"]}
                ],
            }
        )
        assert isinstance(outline, Outline)
        assert outline.sections[0].source_keys == ("p1",)
        with pytest.raises(ValueError, match="sections"):
            outline_from_dict({"title": "x", "sections": []})

    def test_outline_rejects_duplicate_section_ids(self):
        with pytest.raises(ValueError, match="重复"):
            outline_from_dict(
                {
                    "title": "x",
                    "sections": [
                        {"id": "s1", "title": "a"},
                        {"id": "s1", "title": "b"},
                    ],
                }
            )

    def test_gate_report_to_dict(self):
        report = GateReport(ok=False, errors=["bad"], warnings=["warn"], citations=["p1"])
        assert report.to_dict()["ok"] is False
        assert report.to_dict()["citations"] == ["p1"]


def test_paper_json_round_trip_uses_expected_fields():
    data = json.loads(json.dumps(_paper()))
    assert paper_record_from_dict(data).title == "示例论文"


class TestRunStore:
    def test_create_load_and_status(self, tmp_path):
        from backend.literature.run_store import create_run, load_run, run_status

        run = create_run(tmp_path, topic="大模型综述", site_id="xueshu789", run_id="r1")
        assert run.run_dir == tmp_path / "r1"
        assert (run.run_dir / "meta.json").is_file()
        loaded = load_run(run.run_dir)
        assert loaded.topic == "大模型综述"
        status = run_status(run)
        assert status["papers"] == 0
        assert status["has_draft"] is False

    def test_record_papers_dedupes_by_key(self, tmp_path):
        from backend.literature.run_store import create_run, read_jsonl, record_papers

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        added = record_papers(run, [_paper("p1"), _paper("p1"), _paper("p2")])
        assert added == 2
        assert len(read_jsonl(run.run_dir / "papers.jsonl")) == 2

    def test_record_evidence_rejects_unknown_paper(self, tmp_path):
        from backend.literature.run_store import create_run, record_evidence

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        with pytest.raises(ValueError, match="paper_key"):
            record_evidence(
                run,
                [
                    {
                        "evidence_id": "e1",
                        "paper_key": "missing",
                        "kind": "finding",
                        "text": "x",
                    }
                ],
            )

    def test_save_outline_and_draft(self, tmp_path):
        from backend.literature.run_store import (
            create_run,
            load_outline,
            read_draft,
            run_status,
            save_draft,
            save_outline,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        save_outline(run, {"title": "x", "sections": [{"id": "s1", "title": "引言"}]})
        assert load_outline(run).sections[0].id == "s1"
        save_draft(run, "# 草稿\n\n正文 [cite:p1]\n")
        assert "cite:p1" in read_draft(run)
        assert run_status(run)["has_draft"] is True

    def test_invalid_run_dir(self, tmp_path):
        from backend.literature.run_store import load_run

        with pytest.raises(ValueError, match="meta.json"):
            load_run(tmp_path / "missing")


class TestGates:
    def _run(self, tmp_path, record_query_log=True):
        from backend.literature.run_store import (
            create_run,
            record_papers,
            record_query,
            save_draft,
            save_outline,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        if record_query_log:
            record_query(run, "q", "demo", 2)
        record_papers(run, [_paper("p1"), _paper("p2")])
        save_outline(
            run,
            {
                "title": "x",
                "sections": [
                    {"id": "s1", "title": "引言", "source_keys": ["p1"]},
                    {"id": "s2", "title": "方法", "source_keys": ["p2"]},
                ],
            },
        )
        save_draft(run, "# 草稿\n\nP1 的发现 [cite:p1]。\n")
        return run

    def test_extract_citations_orders_and_splits(self):
        from backend.literature.gates import extract_citations

        assert extract_citations("a [cite:p2] b [cite:p1, p2] c [cite:p2]") == [
            "p2",
            "p1",
        ]

    def test_gate_ok_with_unused_warning(self, tmp_path):
        from backend.literature.gates import run_gates

        report = run_gates(self._run(tmp_path))
        assert report.ok is True
        assert report.citations == ["p1"]
        assert any("p2" in w for w in report.warnings)

    def test_unresolved_citation_fails(self, tmp_path):
        from backend.literature.gates import run_gates
        from backend.literature.run_store import save_draft

        run = self._run(tmp_path)
        save_draft(run, "引用不存在的 [cite:missing]")
        report = run_gates(run)
        assert report.ok is False
        assert any("missing" in e for e in report.errors)

    def test_missing_query_log_fails(self, tmp_path):
        from backend.literature.gates import run_gates

        report = run_gates(self._run(tmp_path, record_query_log=False))
        assert any("检索日志" in e for e in report.errors)

    def test_build_references_only_cited(self):
        from backend.literature.gates import build_references
        from backend.literature.models import PaperRecord

        papers = [
            PaperRecord("p1", "论文一", ("张三", "李四"), "2024", "期刊A"),
            PaperRecord("p2", "论文二", ("王五",), "2023", "期刊B"),
        ]
        text, entries = build_references("b [cite:p2] a [cite:p1]", papers)
        assert "[1] 王五. 论文二[J]. 期刊B, 2023." in text
        assert "[2] 张三, 李四. 论文一[J]. 期刊A, 2024." in text
        assert [e["key"] for e in entries] == ["p2", "p1"]


class TestExport:
    def _run(self, tmp_path):
        from backend.literature.gates import run_gates
        from backend.literature.run_store import (
            create_run,
            record_papers,
            record_query,
            save_draft,
            save_outline,
        )

        run = create_run(tmp_path, "t", "demo", run_id="r1")
        record_query(run, "q", "demo", 2)
        record_papers(run, [_paper("p1"), _paper("p2")])
        save_outline(run, {"title": "x", "sections": [{"id": "s1", "title": "引言"}]})
        save_draft(run, "# 草稿\n\n发现 [cite:p1]。\n")
        run_gates(run)
        return run

    def test_export_writes_final_references_and_bibtex(self, tmp_path):
        from backend.literature.export import export_run

        paths = export_run(self._run(tmp_path))
        final = paths["final"].read_text(encoding="utf-8")
        assert "## 参考文献" in final
        assert "[1] 张三. 示例论文[J]. 示例期刊, 2024." in final
        assert "p2" not in paths["references"].read_text(encoding="utf-8")
        assert "@article{p1" in paths["bibtex"].read_text(encoding="utf-8")

    def test_export_fails_when_gate_fails(self, tmp_path):
        from backend.literature.export import export_run
        from backend.literature.run_store import save_draft

        run = self._run(tmp_path)
        save_draft(run, "坏引用 [cite:missing]")
        with pytest.raises(ValueError, match="门禁"):
            export_run(run)

    def test_handoff_has_references(self, tmp_path):
        from backend.literature.export import build_handoff

        data = build_handoff(self._run(tmp_path))
        assert data["references"][0]["key"] == "p1"
        assert data["references"][0]["ref_type"] == "journal"


class _FakeDriver:
    def __init__(self):
        self.navigated = []
        self.clicks = []
        self.snapshot_text = "<tree>results</tree>"
        self.download_path = None
        self.fetched = []
        self.fetch_result = None

    def fetch_text(self, url):
        """快路径能力；默认返回 None 以模拟"不可用"，驱动回落浏览器。"""
        self.fetched.append(url)
        return self.fetch_result

    def navigate(self, url, wait_for=""):
        self.navigated.append((url, wait_for))
        return "https://demo.example/home/1"

    def snapshot(self):
        return self.snapshot_text

    def click(self, target):
        self.clicks.append(target)

    def current_url(self):
        return "https://demo.example/home/1"

    def current_title(self):
        return "文献列表"

    def wait_download(self, timeout_s=60):
        return self.download_path


class TestBrowserSearch:
    def _profile(self):
        from backend.literature.models import profile_from_dict

        return profile_from_dict(_raw_profile())

    def test_search_navigates_and_returns_guidance(self):
        from backend.literature.search import search_with_profile

        driver = _FakeDriver()
        obs = search_with_profile(self._profile(), "机器学习", driver, limit=5)
        assert "demo.example/search" in obs.url
        assert obs.page_url.endswith("/home/1")
        assert "Demo 学术站" in obs.guidance
        assert driver.navigated[0][1] == ".result-list"

    def test_search_prefers_fast_fetch_over_browser(self):
        from backend.literature.search import search_with_profile

        driver = _FakeDriver()
        driver.fetch_result = "# 正文\n结果条目"
        obs = search_with_profile(self._profile(), "机器学习", driver, limit=5)
        assert driver.fetched
        assert "demo.example/search" in driver.fetched[0]
        assert driver.navigated == []
        assert obs.snapshot == "# 正文\n结果条目"
        assert "Demo 学术站" in obs.guidance

    def test_search_falls_back_to_browser_when_fast_fetch_empty(self):
        from backend.literature.search import search_with_profile

        driver = _FakeDriver()
        obs = search_with_profile(self._profile(), "机器学习", driver, limit=5)
        assert driver.fetched
        assert driver.navigated
        assert obs.snapshot == "<tree>results</tree>"

    def test_search_falls_back_to_browser_when_fast_fetch_raises(self):
        from backend.literature.search import search_with_profile

        class _BoomDriver(_FakeDriver):
            def fetch_text(self, url):
                super().fetch_text(url)
                raise RuntimeError("login_required")

        driver = _BoomDriver()
        obs = search_with_profile(self._profile(), "机器学习", driver, limit=5)
        assert driver.navigated
        assert obs.snapshot == "<tree>results</tree>"

    def test_interactive_mode_never_uses_fast_fetch(self):
        from backend.literature.models import profile_from_dict
        from backend.literature.search import search_with_profile

        raw = _raw_profile()
        raw["search"] = {
            "mode": "interactive",
            "url_template": "https://demo.example/entry",
            "entry_url": "https://demo.example/entry",
            "input_selectors": ["input[placeholder*='检索词']"],
            "submit_key": "Enter",
            "wait_after_s": 1,
            "result_hint": "结果条目含下载链接",
        }
        driver = _InteractiveDriver()
        driver.fetch_result = "# 正文"
        obs = search_with_profile(profile_from_dict(raw), "机器学习", driver, limit=5)
        assert driver.fetched == []
        assert obs.snapshot == "<tree>results</tree>"

    def test_download_validates_pdf_and_title(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _FakeDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.4\nfake")
        driver.download_path = str(pdf)
        result = download_pdf(self._profile(), driver, "示例论文", tmp_path)
        assert result.ok is True, result.errors
        assert driver.clicks == ["a.downloadlink"]

    def test_download_rejects_bad_magic(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _FakeDriver()
        bad = tmp_path / "示例论文.pdf"
        bad.write_bytes(b"NOTPDF")
        driver.download_path = str(bad)
        result = download_pdf(self._profile(), driver, "示例论文", tmp_path)
        assert result.ok is False
        assert any("%PDF" in e for e in result.errors)

    def _interstitial_profile(self, **overrides):
        from backend.literature.models import profile_from_dict

        raw = _raw_profile()
        interstitial = {
            "url_contains": ["cnki.net/docdown"],
            "host_fallbacks": ["kns.cnki.net"],
        }
        interstitial.update(overrides)
        raw["pdf"]["interstitial"] = interstitial
        return profile_from_dict(raw)

    def test_download_interstitial_rewrites_host_and_validates(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        pdf = tmp_path / "示例论文.pdf"
        pdf.write_bytes(b"%PDF-1.6\nfake")
        driver.download_path = str(pdf)
        result = download_pdf(
            self._interstitial_profile(),
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
        result = download_pdf(
            self._interstitial_profile(), driver, "示例论文", tmp_path
        )
        assert result.ok is True, result.errors

    def test_download_interstitial_without_tab_fails(self, tmp_path):
        from backend.literature.search import download_pdf

        driver = _InterstitialDriver()
        driver.tabs_state = []
        result = download_pdf(
            self._interstitial_profile(tab_timeout_s=0),
            driver,
            "示例论文",
            tmp_path,
        )
        assert result.ok is False
        assert any("url_contains" in e for e in result.errors)

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


class TestRecording:
    def test_observation_becomes_valid_draft_profile(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore
        from backend.literature.recording import write_profile_draft

        raw = {
            "id": "xueshu789",
            "display_name": "学术资源站",
            "home_url": "https://www.xueshu789.cc/",
            "domains": ["xueshu789.cc"],
            "access": {
                "mode": "browser",
                "login": {
                    "method": "form",
                    "account_label": "您的卡号",
                    "password_label": "您的密码",
                    "url_contains": "/dbList/",
                    "title_not_contains": "登录",
                },
            },
            "search": {
                "url_template": "https://www.xueshu789.cc/dbItem/1?kw={query}",
                "wait_for": [".result-list"],
                "result_fields": {"title": {"selector": ".title"}},
            },
            "pdf": {"entry": {"selector": "a.downloadlink"}},
        }
        out_dir = tmp_path / "sites"
        out_dir.mkdir()
        out_path = out_dir / "xueshu789.yaml"
        profile = write_profile_draft(raw, out_path)
        assert profile.status == "draft"
        assert profile.last_verified_at is not None
        store = SiteProfileStore([ProfileRoot(out_dir, "user")])
        assert store.get("xueshu789").search.wait_for == (".result-list",)


class TestCli:
    def test_init_record_gate_export_flow(self, tmp_path):
        from backend.literature import cli

        root = tmp_path / "runs"
        assert (
            cli.main(
                [
                    "init",
                    "--root",
                    str(root),
                    "--topic",
                    "t",
                    "--site",
                    "demo",
                    "--run-id",
                    "r1",
                ]
            )
            == 0
        )
        run_dir = root / "r1"

        papers = tmp_path / "papers.json"
        papers.write_text(json.dumps([_paper("p1")]), encoding="utf-8")
        assert (
            cli.main(
                [
                    "record-query",
                    "--run",
                    str(run_dir),
                    "--query",
                    "q",
                    "--site",
                    "demo",
                    "--result-count",
                    "1",
                ]
            )
            == 0
        )
        assert (
            cli.main(
                ["record-papers", "--run", str(run_dir), "--json", str(papers)]
            )
            == 0
        )

        outline = tmp_path / "outline.json"
        outline.write_text(
            json.dumps({"title": "x", "sections": [{"id": "s1", "title": "引言"}]}),
            encoding="utf-8",
        )
        assert (
            cli.main(
                ["save-outline", "--run", str(run_dir), "--json", str(outline)]
            )
            == 0
        )

        draft = tmp_path / "draft.md"
        draft.write_text("# 草稿\n\n发现 [cite:p1]。\n", encoding="utf-8")
        assert (
            cli.main(["save-draft", "--run", str(run_dir), "--md", str(draft)]) == 0
        )

        assert cli.main(["gate", "--run", str(run_dir)]) == 0
        assert cli.main(["export", "--run", str(run_dir)]) == 0
        assert (run_dir / "export" / "final.md").is_file()

    def test_gate_failure_exit_code(self, tmp_path):
        from backend.literature import cli

        root = tmp_path / "runs"
        cli.main(
            [
                "init",
                "--root",
                str(root),
                "--topic",
                "t",
                "--site",
                "demo",
                "--run-id",
                "r1",
            ]
        )
        assert cli.main(["gate", "--run", str(root / "r1")]) == 1


class TestEndToEnd:
    def test_synthetic_survey_flow(self, tmp_path):
        from backend.literature.export import export_run
        from backend.literature.gates import run_gates
        from backend.literature.run_store import (
            create_run,
            record_evidence,
            record_papers,
            record_query,
            save_draft,
            save_outline,
        )

        run = create_run(tmp_path, "合成综述", "demo", run_id="e2e")
        record_query(run, "合成", "demo", 3)
        record_papers(run, [_paper("p1"), _paper("p2"), _paper("p3")])
        record_evidence(
            run,
            [
                {"evidence_id": "e1", "paper_key": "p1", "kind": "finding", "text": "A"},
                {"evidence_id": "e2", "paper_key": "p2", "kind": "method", "text": "B"},
            ],
        )
        save_outline(
            run,
            {
                "title": "合成综述",
                "sections": [
                    {"id": "s1", "title": "背景", "source_keys": ["p1"]},
                    {"id": "s2", "title": "方法", "source_keys": ["p2"]},
                ],
            },
        )
        save_draft(run, "# 合成综述\n\n背景 [cite:p1]。\n\n方法 [cite:p2]。\n")
        report = run_gates(run)
        assert report.ok is True
        assert any("p3" in warning for warning in report.warnings)
        paths = export_run(run)
        assert paths["final"].is_file()
        assert paths["bibtex"].is_file()


class _InteractiveDriver(_FakeDriver):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.type_ok = {"input[placeholder*='检索词']": True}
        self._url = "https://demo.example/entry"
        self._title = "入口"

    def navigate(self, url, wait_for=""):
        self.calls.append(("navigate", url, wait_for))
        self._url = "http://proxy.example/search"
        self._title = "检索-中国知网"
        return self._url

    def type_text(self, selector, text, clear=True):
        self.calls.append(("type", selector, text, clear))
        return self.type_ok.get(selector, False)

    def press_key(self, key):
        self.calls.append(("press", key))

    def sleep(self, seconds):
        self.calls.append(("sleep", seconds))

    def click_text(self, text):
        self.calls.append(("click_text", text))

    def current_url(self):
        return self._url

    def current_title(self):
        return self._title


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


class TestInteractiveSearch:
    def _profile(self):
        from backend.literature.models import profile_from_dict

        raw = _raw_profile()
        raw["search"] = {
            "mode": "interactive",
            "url_template": "https://demo.example/entry",
            "entry_url": "https://demo.example/entry",
            "input_selectors": ["#missing", "input[placeholder*='检索词']"],
            "submit_key": "Enter",
            "wait_after_s": 5,
            "result_hint": "结果条目含下载链接",
        }
        return profile_from_dict(raw)

    def test_interactive_search_calls_type_and_press(self):
        from backend.literature.search import search_with_profile

        driver = _InteractiveDriver()
        obs = search_with_profile(self._profile(), "机器学习 综述", driver, limit=5)
        assert ("navigate", "https://demo.example/entry", "") in driver.calls
        assert ("type", "#missing", "机器学习 综述", True) in driver.calls
        assert (
            "type",
            "input[placeholder*='检索词']",
            "机器学习 综述",
            True,
        ) in driver.calls
        assert ("press", "Enter") in driver.calls
        assert ("sleep", 5.0) in driver.calls
        assert "结果条目含下载链接" in obs.guidance
        assert obs.page_url == "http://proxy.example/search"
        assert obs.page_title == "检索-中国知网"

    def test_interactive_search_raises_when_no_input_matches(self):
        from backend.literature.search import search_with_profile

        driver = _InteractiveDriver()
        driver.type_ok = {}
        with pytest.raises(RuntimeError, match="搜索输入框"):
            search_with_profile(self._profile(), "x", driver)


class _FakeCall:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, name, **kwargs):
        self.calls.append((name, kwargs))
        value = self.responses.get(name, {})
        if isinstance(value, Exception):
            raise value
        return value


class TestSageToolDriver:
    def test_maps_calls_and_tracks_page(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_navigate"] = {
            "url": "https://demo.example/entry",
            "title": "入口",
            "browser_meta": {"url": "https://demo.example/entry", "title": "入口"},
        }
        call.responses["browser_snapshot"] = {
            "url": "http://proxy.example/search",
            "title": "检索",
            "elements": [],
        }
        driver = SageToolDriver(call)
        assert driver.navigate("https://demo.example/entry") == "https://demo.example/entry"
        snap = json.loads(driver.snapshot())
        assert snap["url"] == "http://proxy.example/search"
        assert driver.current_title() == "检索"
        assert driver.type_text("input[placeholder*='检索词']", "机器学习") is True
        driver.press_key("Enter")
        driver.click_text("下载")
        names = [name for name, _ in call.calls]
        assert names == [
            "browser_navigate",
            "browser_snapshot",
            "browser_interact",
            "browser_interact",
            "browser_interact",
        ]
        assert call.calls[2][1]["action"] == "type"
        assert call.calls[3][1]["key"] == "Enter"
        assert call.calls[4][1]["text"] == "下载"

    def test_type_text_returns_false_on_tool_error(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_interact"] = RuntimeError("no match")
        assert SageToolDriver(call).type_text("#missing", "x") is False

    def test_wait_download_picks_latest_completed(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["browser_downloads"] = {
            "downloads": [
                {"path": "/a.pdf", "state": "completed", "modified_at": 1},
                {"path": "/b.pdf", "state": "completed", "modified_at": 2},
                {"path": "/c.crdownload", "state": "in_progress", "modified_at": 3},
            ]
        }
        assert SageToolDriver(call).wait_download() == "/b.pdf"

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

    def test_fetch_text_returns_content_and_tracks_page(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["web_fetch"] = {
            "url": "https://demo.example/search?q=x",
            "title": "检索结果",
            "content": "# 正文",
        }
        driver = SageToolDriver(call)
        assert driver.fetch_text("https://demo.example/search?q=x") == "# 正文"
        assert driver.current_url() == "https://demo.example/search?q=x"
        assert driver.current_title() == "检索结果"
        assert [name for name, _ in call.calls] == ["web_fetch"]

    def test_fetch_text_returns_none_on_tool_error(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["web_fetch"] = RuntimeError("login_required: 仍被要求登录")
        assert SageToolDriver(call).fetch_text("https://demo.example/") is None

    def test_fetch_text_returns_none_on_empty_body(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["web_fetch"] = {"url": "https://demo.example/", "content": "  "}
        assert SageToolDriver(call).fetch_text("https://demo.example/") is None

    def test_interaction_after_fetch_navigates_browser_lazily(self):
        from backend.literature.sage_driver import SageToolDriver

        call = _FakeCall()
        call.responses["web_fetch"] = {
            "url": "https://demo.example/search?q=x",
            "content": "# 正文",
        }
        call.responses["browser_navigate"] = {
            "url": "https://demo.example/search?q=x",
            "title": "检索结果",
        }
        driver = SageToolDriver(call)
        driver.fetch_text("https://demo.example/search?q=x")
        driver.click("a.downloadlink")
        assert [name for name, _ in call.calls] == [
            "web_fetch",
            "browser_navigate",
            "browser_interact",
        ]
