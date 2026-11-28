"""指导文本中的站点经验与后端（spec §3.1 / §3.2）。"""

import pytest

from backend.literature.guidance import STALE_AFTER_DAYS, render_search_guidance
from backend.literature.models import profile_from_dict

pytestmark = pytest.mark.unit

_BASE = {
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


def _profile(notes=None, backends=None):
    raw = dict(_BASE)
    if notes:
        raw["notes"] = notes
    if backends:
        raw["backends"] = backends
    return profile_from_dict(raw)


def test_no_notes_section_when_there_are_no_notes() -> None:
    text = render_search_guidance(_profile(), "关键词")
    assert "站点经验" not in text


def test_notes_section_lists_notes_sorted_by_severity() -> None:
    profile = _profile(
        notes=[
            {
                "id": "cosmetic-one",
                "title": "只是提示",
                "symptom": "s",
                "workaround": "w",
                "severity": "cosmetic",
                "learned_at": "2026-01-01",
            },
            {
                "id": "blocker-one",
                "title": "阻断问题",
                "symptom": "s",
                "workaround": "w",
                "severity": "blocker",
                "learned_at": "2026-01-01",
            },
            {
                "id": "degraded-one",
                "title": "降级问题",
                "symptom": "s",
                "workaround": "w",
                "severity": "degraded",
                "learned_at": "2026-01-01",
            },
        ]
    )
    text = render_search_guidance(profile, "关键词")
    assert "站点经验" in text
    assert text.index("阻断问题") < text.index("降级问题") < text.index("只是提示")


def test_only_notes_relevant_to_the_phase_are_rendered() -> None:
    profile = _profile(
        notes=[
            {
                "id": "download-note",
                "title": "下载相关",
                "symptom": "s",
                "workaround": "w",
                "severity": "blocker",
                "applies_to": ["pdf.download"],
                "learned_at": "2026-01-01",
            }
        ]
    )
    search_text = render_search_guidance(profile, "关键词", phase="search")
    assert "下载相关" not in search_text
    download_text = render_search_guidance(profile, "关键词", phase="pdf.download")
    assert "下载相关" in download_text


def test_blocked_backend_is_flagged_for_manual_action() -> None:
    profile = _profile(
        backends=[
            {
                "id": "db1",
                "label": "需滑块的库",
                "entry_url": "https://demo.example/dbItem/1",
                "status": "blocked",
                "reason": "触发滑块验证",
            }
        ]
    )
    text = render_search_guidance(profile, "关键词")
    assert "db1" in text
    assert "滑块" in text or "人工" in text


def test_ready_backend_is_listed_as_candidate() -> None:
    profile = _profile(
        backends=[
            {
                "id": "db3",
                "label": "可用库",
                "entry_url": "https://demo.example/dbItem/3",
                "status": "ready",
            }
        ]
    )
    text = render_search_guidance(profile, "关键词")
    assert "db3" in text


def test_stale_after_days_constant() -> None:
    assert STALE_AFTER_DAYS == 180
