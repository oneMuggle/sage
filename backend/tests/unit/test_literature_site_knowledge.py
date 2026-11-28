"""站点知识模型：notes[] / backends[]（spec §3.1 / §3.2）。"""

import pytest

from backend.literature.models import (
    BACKEND_STATUSES,
    NOTE_SEVERITIES,
    SiteProfileError,
    profile_from_dict,
    render_search_url,
    select_backend,
    select_backend_id,
)

pytestmark = pytest.mark.unit

_MINIMAL = {
    "id": "demo",
    "display_name": "演示站",
    "home_url": "https://demo.example",
    "domains": ["demo.example"],
    "search": {
        "url_template": "https://demo.example/s?q={query}&n={limit}",
        "mode": "url",
        "submit_key": "Enter",
        "result_hint": "",
    },
}


def test_minimal_profile_has_no_notes_or_backends() -> None:
    profile = profile_from_dict(dict(_MINIMAL))
    assert profile.notes == ()
    assert profile.backends == ()


def test_notes_are_parsed() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "download-ddata-missing",
            "title": "结果行 href 必须取元素属性",
            "symptom": "下载报参数错误",
            "cause": "快照 URL 被截断",
            "workaround": "用 browser_interact action=attr 读 href",
            "severity": "blocker",
            "applies_to": ["pdf.entry"],
            "learned_at": "2026-01-15",
            "verified_at": "2026-02-03",
            "source_run": "run-001",
        }
    ]
    profile = profile_from_dict(raw)
    assert len(profile.notes) == 1
    note = profile.notes[0]
    assert note.id == "download-ddata-missing"
    assert note.severity == "blocker"
    assert note.applies_to == ("pdf.entry",)
    assert note.learned_at == "2026-01-15"
    assert note.verified_at == "2026-02-03"
    assert note.source_run == "run-001"


def test_note_severity_is_validated() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "x",
            "title": "t",
            "symptom": "s",
            "workaround": "w",
            "severity": "catastrophic",
            "learned_at": "2026-01-15",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_note_id_must_be_slug() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "Bad Id",
            "title": "t",
            "symptom": "s",
            "workaround": "w",
            "severity": "blocker",
            "learned_at": "2026-01-15",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_note_learned_at_must_be_iso_date() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "x",
            "title": "t",
            "symptom": "s",
            "workaround": "w",
            "severity": "blocker",
            "learned_at": "2026/01/15",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_duplicate_note_ids_are_overridden_not_appended() -> None:
    raw = dict(_MINIMAL)
    raw["notes"] = [
        {
            "id": "dup",
            "title": "第一版",
            "symptom": "s",
            "workaround": "w",
            "severity": "blocker",
            "learned_at": "2026-01-15",
        },
        {
            "id": "dup",
            "title": "第二版",
            "symptom": "s2",
            "workaround": "w2",
            "severity": "degraded",
            "learned_at": "2026-01-16",
        },
    ]
    profile = profile_from_dict(raw)
    assert len(profile.notes) == 1
    assert profile.notes[0].title == "第二版"


def test_backends_are_parsed() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {
            "id": "db3",
            "label": "库三",
            "entry_url": "https://demo.example/dbItem/3",
            "status": "ready",
            "capabilities": {"search": True},
            "checked_at": "2026-01-15",
        },
        {
            "id": "db1",
            "label": "库一",
            "entry_url": "https://demo.example/dbItem/1",
            "status": "unavailable",
            "reason": "代理报错",
        },
    ]
    profile = profile_from_dict(raw)
    assert len(profile.backends) == 2
    assert profile.backends[0].id == "db3"
    assert profile.backends[0].capabilities == {"search": True}
    assert profile.backends[1].reason == "代理报错"


def test_backend_status_is_validated() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {
            "id": "db9",
            "label": "库九",
            "entry_url": "https://demo.example/dbItem/9",
            "status": "maybe",
        }
    ]
    with pytest.raises(SiteProfileError):
        profile_from_dict(raw)


def test_select_backend_prefers_requested_id() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {"id": "db1", "label": "一", "entry_url": "https://demo.example/dbItem/1", "status": "ready"},
        {"id": "db2", "label": "二", "entry_url": "https://demo.example/dbItem/2", "status": "ready"},
    ]
    profile = profile_from_dict(raw)
    assert select_backend(profile, "db2").id == "db2"
    assert select_backend_id(profile) == "db1"


def test_select_backend_id_skips_blocked_and_unavailable() -> None:
    raw = dict(_MINIMAL)
    raw["backends"] = [
        {"id": "db1", "label": "一", "entry_url": "https://demo.example/dbItem/1", "status": "blocked"},
        {"id": "db2", "label": "二", "entry_url": "https://demo.example/dbItem/2", "status": "unavailable"},
        {"id": "db3", "label": "三", "entry_url": "https://demo.example/dbItem/3", "status": "ready"},
    ]
    profile = profile_from_dict(raw)
    assert select_backend_id(profile) == "db3"


def test_render_search_url_supports_backend_id_placeholder() -> None:
    raw = dict(_MINIMAL)
    raw["search"] = dict(_MINIMAL["search"])  # type: ignore[index]
    raw["search"]["url_template"] = "https://demo.example/s?q={query}&db={backend_id}&n={limit}"
    raw["backends"] = [
        {"id": "db3", "label": "三", "entry_url": "https://demo.example/dbItem/3", "status": "ready"},
    ]
    profile = profile_from_dict(raw)
    url = render_search_url(profile, "关键词", limit=5, backend_id="db3")
    assert "db=db3" in url
    assert "q=%E5%85%B3%E9%94%AE%E8%AF%8D" in url


def test_compliance_contact_email_is_parsed() -> None:
    raw = dict(_MINIMAL)
    raw["compliance"] = {"note": "遵守条款", "contact_email": "user@example.org"}
    profile = profile_from_dict(raw)
    assert profile.compliance.contact_email == "user@example.org"


def test_enum_constants() -> None:
    assert NOTE_SEVERITIES == ("blocker", "degraded", "cosmetic")
    assert BACKEND_STATUSES == ("ready", "blocked", "unavailable", "unknown")


def _write_main_profile(directory, site_id="demo", extra=""):
    directory.mkdir(parents=True, exist_ok=True)
    payload = (
        "id: demo\n"
        "display_name: 演示站\n"
        "home_url: https://demo.example\n"
        "domains:\n  - demo.example\n"
        "search:\n"
        "  url_template: https://demo.example/s?q={query}&n={limit}\n"
        "  mode: url\n"
        "  submit_key: Enter\n"
        "  result_hint: ''\n" + extra
    )
    path = directory / f"{site_id}.yaml"
    path.write_text(payload, encoding="utf-8")
    return path


def test_sidecar_suffixes() -> None:
    from backend.literature.knowledge import (
        BACKENDS_SIDECAR_SUFFIX,
        NOTES_SIDECAR_SUFFIX,
    )

    assert NOTES_SIDECAR_SUFFIX == ".notes.yaml"
    assert BACKENDS_SIDECAR_SUFFIX == ".backends.yaml"


def test_is_sidecar_filename() -> None:
    from backend.literature.knowledge import is_sidecar_filename

    assert is_sidecar_filename("demo.notes.yaml") is True
    assert is_sidecar_filename("demo.backends.yaml") is True
    assert is_sidecar_filename("demo.yaml") is False


def test_profile_store_skips_sidecar_files(tmp_path) -> None:
    from backend.literature.profile_store import ProfileRoot, SiteProfileStore

    _write_main_profile(tmp_path)
    (tmp_path / "demo.notes.yaml").write_text("notes: []\n", encoding="utf-8")
    store = SiteProfileStore([ProfileRoot(tmp_path, "user")])
    assert store.list_ids() == ["demo"]


def test_profile_store_merges_sidecar_notes(tmp_path) -> None:
    from backend.literature.profile_store import ProfileRoot, SiteProfileStore

    _write_main_profile(
        tmp_path,
        extra=(
            "notes:\n"
            "  - id: base-note\n"
            "    title: 基线\n"
            "    symptom: s\n"
            "    workaround: w\n"
            "    severity: degraded\n"
            "    learned_at: '2026-01-01'\n"
        ),
    )
    (tmp_path / "demo.notes.yaml").write_text(
        "notes:\n"
        "  - id: base-note\n"
        "    title: 覆盖版\n"
        "    symptom: s2\n"
        "    workaround: w2\n"
        "    severity: blocker\n"
        "    learned_at: '2026-02-01'\n"
        "  - id: extra-note\n"
        "    title: 新增\n"
        "    symptom: s3\n"
        "    workaround: w3\n"
        "    severity: cosmetic\n"
        "    learned_at: '2026-02-02'\n",
        encoding="utf-8",
    )
    store = SiteProfileStore([ProfileRoot(tmp_path, "user")])
    profile = store.get("demo")
    ids = [note.id for note in profile.notes]
    assert "extra-note" in ids
    titles = {note.id: note.title for note in profile.notes}
    assert titles["base-note"] == "覆盖版"


def test_broken_sidecar_raises_explicit_error(tmp_path) -> None:
    from backend.literature.models import SiteProfileError
    from backend.literature.profile_store import ProfileRoot, SiteProfileStore

    _write_main_profile(tmp_path)
    (tmp_path / "demo.notes.yaml").write_text("notes: [\n  - broken\n", encoding="utf-8")
    store = SiteProfileStore([ProfileRoot(tmp_path, "user")])
    with pytest.raises(SiteProfileError):
        store.get("demo")


def test_write_sidecar_is_atomic(tmp_path) -> None:
    from backend.literature.knowledge import write_sidecar

    target = tmp_path / "demo.notes.yaml"
    write_sidecar(target, {"notes": []})
    assert target.is_file()
    assert not list(tmp_path.glob(".tmp-*"))
