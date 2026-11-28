"""Unpaywall OA 可得性轴（spec §7.3）。"""

import pytest

from backend.literature.models import PaperRecord, profile_from_dict
from backend.literature.verify import (
    ACCESS_STATUSES,
    UnpaywallLookup,
    build_oa_lookups,
    merge_access_status,
)

pytestmark = pytest.mark.unit


def _paper(doi: str = "10.1000/xyz") -> PaperRecord:
    """构造真正的 PaperRecord —— ``_doi_of`` 读属性，不接受 dict。"""
    return PaperRecord(paper_key="doi:" + doi, title="示例题名", doi=doi)


def test_lookup_without_email_is_unavailable() -> None:
    lookup = UnpaywallLookup(contact_email="")
    assert lookup.available is False
    assert lookup.name == "unpaywall"


def test_lookup_with_email_is_available() -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")
    assert lookup.available is True


def test_lookup_without_doi_returns_none() -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")
    assert lookup.lookup(PaperRecord(paper_key="cnki:demo", title="无 DOI")) is None


def test_lookup_parses_oa_response(monkeypatch) -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")

    def fake_get(url):
        return {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {"url_for_pdf": "https://repo.example/paper.pdf"},
        }

    monkeypatch.setattr("backend.literature.verify._get_json", fake_get)
    result = lookup.lookup(_paper("10.1000/xyz"))
    assert result is not None
    assert result["is_oa"] is True
    assert result["oa_status"] == "green"
    assert result["best_oa_url"] == "https://repo.example/paper.pdf"
    assert result["access_status"] == "oa"


def test_lookup_marks_closed_access(monkeypatch) -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")

    def fake_get(url):
        return {"is_oa": False, "oa_status": "closed"}

    monkeypatch.setattr("backend.literature.verify._get_json", fake_get)
    result = lookup.lookup(_paper("10.1000/abc"))
    assert result is not None
    assert result["is_oa"] is False
    assert result["access_status"] == "closed"


def test_lookup_returns_none_when_service_has_no_record(monkeypatch) -> None:
    lookup = UnpaywallLookup(contact_email="user@example.org")
    monkeypatch.setattr("backend.literature.verify._get_json", lambda url: None)
    assert lookup.lookup(_paper("10.1000/none")) is None


def test_lookup_skips_second_call_inside_min_interval(monkeypatch) -> None:
    """最小间隔节流：窗口内的重复查询不发请求（spec §7.3 限流与礼貌）。"""
    calls = []

    def fake_get(url):
        calls.append(url)
        return {"is_oa": True, "oa_status": "gold"}

    monkeypatch.setattr("backend.literature.verify._get_json", fake_get)
    lookup = UnpaywallLookup(contact_email="user@example.org", min_interval_s=60.0)
    assert lookup.lookup(_paper("10.1000/one")) is not None
    assert lookup.lookup(_paper("10.1000/two")) is None
    assert len(calls) == 1


def _profile(contact_email: str = "") -> object:
    raw = {
        "id": "demo",
        "display_name": "演示站",
        "home_url": "https://demo.example",
        "domains": ["demo.example"],
        "search": {
            "url_template": "https://demo.example/s?q={query}",
            "mode": "url",
            "submit_key": "Enter",
            "result_hint": "",
        },
    }
    if contact_email:
        raw["compliance"] = {"contact_email": contact_email}
    return profile_from_dict(raw)


def test_merge_access_status_prefers_subscription() -> None:
    assert merge_access_status("oa", "subscription") == "subscription"
    assert merge_access_status("closed", "oa") == "oa"
    assert merge_access_status("closed", "unknown") == "closed"
    assert merge_access_status() == "unknown"


def test_access_status_vocabulary_is_shared_with_download_path() -> None:
    """四态词汇由 verify 独占；下载路径用的是同一套字面量（spec §7.3）。"""
    from backend.literature.search import DownloadResult

    assert set(ACCESS_STATUSES) == {"subscription", "oa", "closed", "unknown"}
    assert DownloadResult(path=None, ok=False).access_status == "unknown"
    assert "subscription" in ACCESS_STATUSES


def test_build_oa_lookups_is_empty_without_email() -> None:
    assert build_oa_lookups(_profile()) == []


def test_build_oa_lookups_includes_unpaywall_with_email() -> None:
    lookups = build_oa_lookups(_profile("user@example.org"))
    assert [item.name for item in lookups] == ["unpaywall"]
    assert lookups[0].available is True


def test_oa_axis_does_not_pollute_metadata_axis() -> None:
    """OA 轴与元数据轴分开 —— 混进 default_lookups() 会污染核验报告。"""
    from backend.literature.verify import default_lookups

    names = {item.name for item in default_lookups()}
    assert "unpaywall" not in names
    assert names == {"crossref", "openalex", "semantic_scholar"}


def test_verify_run_access_writes_report(tmp_path, monkeypatch) -> None:
    from backend.literature.run_store import create_run, record_papers
    from backend.literature.verify import verify_run_access

    monkeypatch.setattr(
        "backend.literature.verify._get_json",
        lambda url: {
            "is_oa": True,
            "oa_status": "green",
            "best_oa_location": {"url_for_pdf": "https://repo.example/p.pdf"},
        },
    )
    run = create_run(tmp_path, "t", "demo", run_id="r1")
    record_papers(
        run,
        [{"paper_key": "doi:10.1/demo", "title": "示例论文", "doi": "10.1/demo"}],
    )
    report = verify_run_access(run, profile=_profile("user@example.org"))
    assert report["items"][0]["access_status"] == "oa"
    assert report["items"][0]["best_oa_url"] == "https://repo.example/p.pdf"
    assert (run.run_dir / "access_verification.json").is_file()


def test_verify_run_access_without_email_marks_unknown(tmp_path) -> None:
    from backend.literature.run_store import create_run, record_papers
    from backend.literature.verify import verify_run_access

    run = create_run(tmp_path, "t", "demo", run_id="r2")
    record_papers(
        run,
        [{"paper_key": "doi:10.1/demo", "title": "示例论文", "doi": "10.1/demo"}],
    )
    report = verify_run_access(run, profile=_profile())
    assert report["items"][0]["access_status"] == "unknown"


def test_cli_verify_access_command(tmp_path, capsys) -> None:
    """CLI 入口可达：``--site`` 省略时不配 OA 轴，全部判为 unknown。"""
    import json as _json

    from backend.literature.cli import main
    from backend.literature.run_store import create_run, record_papers

    run = create_run(tmp_path, "t", "demo", run_id="r3")
    record_papers(
        run,
        [{"paper_key": "doi:10.1/demo", "title": "示例论文", "doi": "10.1/demo"}],
    )
    code = main(["verify-access", "--run", str(run.run_dir)])
    assert code == 0
    payload = _json.loads(capsys.readouterr().out.strip())
    assert payload["ok"] is True
    assert payload["items"][0]["access_status"] == "unknown"
