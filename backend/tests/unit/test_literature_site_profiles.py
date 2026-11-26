"""SiteProfile 领域模型 / 存储 / 适配器单元测试。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from backend.literature.models import (
    PaperRecord,
    SiteProfileError,
    is_logged_in,
    profile_from_dict,
    render_search_url,
)

pytestmark = pytest.mark.unit


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


class TestProfileModel:
    def test_minimal_profile_parses(self):
        profile = profile_from_dict(_raw_profile())
        assert profile.id == "demo"
        assert profile.display_name == "Demo 学术站"
        assert profile.access.mode == "browser"
        assert profile.access.login.account_label == "卡号"
        assert profile.search.wait_for == (".result-list",)
        assert profile.pdf is not None
        assert profile.pdf.entry_selector == "a.downloadlink"
        assert profile.status == "ready"
        assert profile.source_layer == "builtin"

    def test_parses_detail_url_from(self):
        raw = _raw_profile()
        raw["detail"] = {
            "open_by": "click_text",
            "url_from": {"selector": "a.downloadlink", "param": "url", "decode": "base64"},
            "fields": {"abstract": {"selector": "#ChDivSummary"}},
        }
        profile = profile_from_dict(raw)
        assert profile.detail is not None
        assert profile.detail.url_from is not None
        assert profile.detail.url_from.selector == "a.downloadlink"
        assert profile.detail.url_from.param == "url"
        assert profile.detail.url_from.decode == "base64"
        assert profile.detail.fields["abstract"].selector == "#ChDivSummary"

    def test_detail_url_from_defaults_decode_none(self):
        raw = _raw_profile()
        raw["detail"] = {"url_from": {"selector": "a", "param": "u"}}
        profile = profile_from_dict(raw)
        assert profile.detail.url_from.decode == "none"

    def test_rejects_detail_url_from_without_param(self):
        raw = _raw_profile()
        raw["detail"] = {"url_from": {"selector": "a"}}
        with pytest.raises(SiteProfileError, match="url_from.param"):
            profile_from_dict(raw)

    def test_rejects_detail_url_from_bad_decode(self):
        raw = _raw_profile()
        raw["detail"] = {"url_from": {"selector": "a", "param": "u", "decode": "rot13"}}
        with pytest.raises(SiteProfileError, match="decode"):
            profile_from_dict(raw)

    def test_rejects_invalid_id(self):
        with pytest.raises(SiteProfileError, match="id"):
            profile_from_dict(_raw_profile(id="Bad ID"))

    def test_rejects_missing_domains(self):
        with pytest.raises(SiteProfileError, match="domains"):
            profile_from_dict(_raw_profile(domains=[]))

    def test_rejects_unknown_access_mode(self):
        raw = _raw_profile()
        raw["access"]["mode"] = "magic"
        with pytest.raises(SiteProfileError, match="access.mode"):
            profile_from_dict(raw)

    def test_rejects_url_template_without_query_placeholder(self):
        raw = _raw_profile()
        raw["search"]["url_template"] = "https://demo.example/search"
        with pytest.raises(SiteProfileError, match="\\{query\\}"):
            profile_from_dict(raw)

    def test_rejects_non_http_home_url(self):
        with pytest.raises(SiteProfileError, match="home_url"):
            profile_from_dict(_raw_profile(home_url="file:///etc/passwd"))

    def test_rejects_bad_last_verified_at(self):
        with pytest.raises(SiteProfileError, match="last_verified_at"):
            profile_from_dict(_raw_profile(last_verified_at="2026/11/21"))


class TestUrlRendering:
    def test_encodes_chinese_query_and_limit(self):
        profile = profile_from_dict(_raw_profile())
        url = render_search_url(profile, "机器学习 综述", limit=5)
        parsed = urlparse(url)
        assert parsed.netloc == "demo.example"
        qs = parse_qs(parsed.query)
        assert qs["q"] == ["机器学习 综述"]
        assert qs["n"] == ["5"]

    def test_rejects_empty_query(self):
        profile = profile_from_dict(_raw_profile())
        with pytest.raises(SiteProfileError, match="query"):
            render_search_url(profile, "   ")

    def test_rejects_host_outside_domains(self):
        raw = _raw_profile()
        raw["search"]["url_template"] = "https://evil.example/x?q={query}"
        profile = profile_from_dict(raw)
        with pytest.raises(SiteProfileError, match="域名"):
            render_search_url(profile, "x")


class TestLoginCheck:
    def test_logged_in_when_all_checks_pass(self):
        profile = profile_from_dict(_raw_profile())
        assert is_logged_in(profile, "https://demo.example/home/1", "文献列表") is True

    def test_not_logged_in_when_url_check_fails(self):
        profile = profile_from_dict(_raw_profile())
        assert is_logged_in(profile, "https://demo.example/login", "文献列表") is False

    def test_not_logged_in_when_title_check_fails(self):
        profile = profile_from_dict(_raw_profile())
        assert is_logged_in(profile, "https://demo.example/home/1", "登录 - Demo") is False

    def test_unknown_when_no_checks_configured(self):
        raw = _raw_profile()
        raw["access"]["login"] = {"method": "manual"}
        profile = profile_from_dict(raw)
        assert is_logged_in(profile, None, None) is None


class TestPaperRecord:
    def test_round_trip_to_dict(self):
        record = PaperRecord(
            paper_key="doi:10.1000/demo",
            title="示例论文",
            authors=("张三", "李四"),
            year="2026",
            source_site="demo",
            source_query="示例",
        )
        data = record.to_dict()
        assert data["authors"] == ["张三", "李四"]
        assert data["paper_key"] == "doi:10.1000/demo"
        assert data["source_site"] == "demo"


class TestProfileStore:
    @staticmethod
    def _write(root: Path, filename: str, site_id: str, title: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        body = (
            f"id: {site_id}\n"
            f"display_name: {title}\n"
            "home_url: https://demo.example/\n"
            "domains: [demo.example]\n"
            "search:\n"
            "  url_template: https://demo.example/s?q={query}\n"
        )
        (root / filename).write_text(body, encoding="utf-8")

    def test_precedence_project_over_user_over_builtin(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        builtin = tmp_path / "builtin"
        user = tmp_path / "user"
        project = tmp_path / "project"
        self._write(builtin, "demo.yaml", "demo", "Builtin")
        self._write(user, "demo.yaml", "demo", "User")
        self._write(project, "demo.yaml", "demo", "Project")

        store = SiteProfileStore(
            [
                ProfileRoot(builtin, "builtin"),
                ProfileRoot(user, "user"),
                ProfileRoot(project, "project"),
            ]
        )
        profiles = store.discover()
        assert profiles["demo"].display_name == "Project"
        assert profiles["demo"].source_layer == "project"

    def test_invalid_profile_is_skipped_and_get_raises(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        root = tmp_path / "sites"
        root.mkdir()
        (root / "bad.yaml").write_text("id: Bad ID\n", encoding="utf-8")
        self._write(root, "good.yaml", "good", "Good")

        store = SiteProfileStore([ProfileRoot(root, "user")])
        profiles = store.discover()
        assert "good" in profiles
        with pytest.raises(SiteProfileError, match="无效"):
            store.get("bad")

    def test_get_unknown_lists_available(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        root = tmp_path / "sites"
        self._write(root, "good.yaml", "good", "Good")
        store = SiteProfileStore([ProfileRoot(root, "user")])
        with pytest.raises(SiteProfileError, match="good"):
            store.get("missing")

    def test_default_store_uses_env_dir(self, tmp_path, monkeypatch):
        from backend.literature import profile_store

        user_dir = tmp_path / "user-sites"
        self._write(user_dir, "envsite.yaml", "envsite", "Env Site")
        monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(user_dir))
        monkeypatch.chdir(tmp_path)
        profile_store.reset_default_store()

        store = profile_store.get_default_store()
        assert "envsite" in store.list_ids()
        profile_store.reset_default_store()


class TestGuidance:
    def test_contains_site_login_selectors_and_compliance(self):
        from backend.literature.guidance import render_search_guidance

        profile = profile_from_dict(_raw_profile())
        text = render_search_guidance(profile, "机器学习", limit=5)
        assert "Demo 学术站" in text
        assert "demo.example" in text
        assert "卡号" in text
        assert ".result-list" in text
        assert "a.downloadlink" in text
        assert "仅个人学习" in text
        assert "{query}" not in text

    def test_renders_detail_url_from(self):
        from backend.literature.guidance import render_search_guidance

        raw = _raw_profile()
        raw["detail"] = {
            "url_from": {"selector": "a.downloadlink", "param": "url", "decode": "base64"},
            "fields": {"abstract": {"selector": "#ChDivSummary"}},
        }
        text = render_search_guidance(profile_from_dict(raw), "x")
        assert "详情 URL 推导" in text
        assert "取查询参数 url" in text
        assert "decode=base64" in text

    def test_reports_login_state(self):
        from backend.literature.guidance import render_search_guidance

        profile = profile_from_dict(_raw_profile())
        logged = render_search_guidance(
            profile, "x", page_url="https://demo.example/home/1", page_title="文献列表"
        )
        assert "登录态: 已登录" in logged
        anonymous = render_search_guidance(
            profile, "x", page_url="https://demo.example/login", page_title="登录"
        )
        assert "登录态: 未登录" in anonymous


class TestProfileBackedAdapter:
    def test_satisfies_existing_adapter_protocol(self):
        from backend.literature.academic_adapter import ProfileBackedAdapter
        from backend.skills.builtin.academic_adapters import AcademicSiteAdapter

        profile = profile_from_dict(_raw_profile())
        adapter = ProfileBackedAdapter(profile)
        assert adapter.name == "demo"
        assert isinstance(adapter, AcademicSiteAdapter)
        assert "demo.example" in adapter.build_search_url("x")
        assert "Demo 学术站" in adapter.render_guidance("x")

    def test_get_site_adapter_falls_back_to_profile_store(self, tmp_path, monkeypatch):
        from backend.literature import profile_store
        from backend.skills.builtin import academic_adapters

        sites = tmp_path / "user-sites"
        sites.mkdir()
        (sites / "demo.yaml").write_text(
            "id: demo\n"
            "display_name: Demo\n"
            "home_url: https://demo.example/\n"
            "domains: [demo.example]\n"
            "search:\n"
            "  url_template: https://demo.example/s?q={query}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(sites))
        monkeypatch.chdir(tmp_path)
        profile_store.reset_default_store()
        academic_adapters._DEFAULT_ADAPTERS.pop("demo", None)

        adapter = academic_adapters.get_site_adapter("demo")
        assert adapter.name == "demo"
        assert "demo.example" in adapter.build_search_url("x")

        profile_store.reset_default_store()
        academic_adapters._DEFAULT_ADAPTERS.pop("demo", None)


class TestTemplateXueshu789Profile:
    """xueshu789 是示例模板（docs/templates），不是 builtin 产品配置。"""

    def test_template_profile_loads_and_matches_observed_facts(self):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        template_dir = (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "templates"
            / "literature-sites"
        )
        store = SiteProfileStore([ProfileRoot(template_dir, "template")])
        profile = store.get("xueshu789")
        assert profile.display_name == "学术资源站"
        assert "xueshu789.cc" in profile.domains
        assert "82.157.23.222" in profile.domains
        assert profile.access.login.method == "form"
        assert profile.access.login.url_contains == "/dbList/"
        assert profile.search.mode == "interactive"
        assert profile.search.entry_url == "https://www.xueshu789.cc/dbItem/3"
        assert "input[placeholder*='检索词']" in profile.search.input_selectors
        assert profile.pdf is not None
        assert profile.pdf.entry_selector == "a.downloadlink"
        assert profile.pdf.entry_text == "下载"
        assert profile.pdf.post_click_wait_s == 8.0
        assert profile.status == "ready"
        assert profile.last_verified_at == "2026-11-22"
        assert profile.compliance.default_enabled is False
        assert profile.source_layer == "template"

    def test_builtin_sites_dir_ships_no_concrete_sites(self):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        builtin = Path(__file__).resolve().parents[2] / "literature" / "sites"
        store = SiteProfileStore([ProfileRoot(builtin, "builtin")])
        assert store.list_ids() == []


class TestInteractiveSearchProfile:
    def _interactive_raw(self):
        raw = _raw_profile()
        raw["search"] = {
            "mode": "interactive",
            "url_template": "https://demo.example/entry",
            "entry_url": "https://demo.example/entry",
            "input_selectors": ["input[placeholder*='检索词']"],
            "submit_key": "Enter",
            "wait_after_s": 5,
            "result_hint": "每条结果含下载链接",
        }
        return raw

    def test_interactive_profile_parses(self):
        profile = profile_from_dict(self._interactive_raw())
        assert profile.search.mode == "interactive"
        assert profile.search.entry_url == "https://demo.example/entry"
        assert profile.search.input_selectors == ("input[placeholder*='检索词']",)
        assert profile.search.submit_key == "Enter"
        assert profile.search.wait_after_s == 5.0

    def test_interactive_requires_input_selectors(self):
        raw = self._interactive_raw()
        raw["search"].pop("input_selectors")
        with pytest.raises(SiteProfileError, match="input_selectors"):
            profile_from_dict(raw)

    def test_interactive_guidance_contains_flow(self):
        from backend.literature.guidance import render_search_guidance

        profile = profile_from_dict(self._interactive_raw())
        text = render_search_guidance(profile, "机器学习")
        assert "检索模式: 交互式" in text
        assert "https://demo.example/entry" in text
        assert "input[placeholder*='检索词']" in text
        assert "press Enter" in text
        assert "每条结果含下载链接" in text

    def test_pdf_post_click_and_note(self):
        raw = _raw_profile()
        raw["pdf"] = {
            "entry": {"text": "下载"},
            "post_click_wait_s": 8,
            "note": "待验证",
        }
        profile = profile_from_dict(raw)
        assert profile.pdf.post_click_wait_s == 8.0
        assert profile.pdf.note == "待验证"
