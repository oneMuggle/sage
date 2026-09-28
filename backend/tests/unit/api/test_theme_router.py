"""R69 — theme 路由单元测试。

直接调用路由函数（同步），ThemeStorage 打桩。覆盖：save/list/delete/get
透传、get 未命中 404、ThemeCssPayload 字段校验（name 长度、appearance
枚举、css 长度）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import theme_router as tr

pytestmark = pytest.mark.unit


def _payload(**overrides):
    base = {
        "id": "theme-1",
        "name": "My Theme",
        "cover": None,
        "css": "body { color: #333; }",
        "appearance": "light",
        "created_at": 1700000000000,
        "updated_at": 1700000001000,
    }
    base.update(overrides)
    return tr.ThemeCssPayload(**base)


@pytest.fixture()
def fake_storage(monkeypatch):
    state = {"saved": None, "deleted_id": None}
    storage = SimpleNamespace(
        save=lambda data: state.update(saved=data) or "new-id",
        list=lambda: [{"id": "theme-1"}, {"id": "theme-2"}],
        delete=lambda theme_id: state.update(deleted_id=theme_id) or True,
        get=lambda theme_id: {"id": theme_id, "name": "My Theme"}
        if theme_id == "theme-1"
        else None,
    )
    monkeypatch.setattr(tr, "_storage", storage)
    return state


def test_save_theme_returns_id(fake_storage):
    payload = _payload()
    out = tr.save_theme(payload)
    assert out == {"id": "new-id"}
    assert fake_storage["saved"]["id"] == "theme-1"


def test_list_themes_passthrough(fake_storage):
    out = tr.list_themes()
    assert [t["id"] for t in out] == ["theme-1", "theme-2"]


def test_delete_theme_returns_ok(fake_storage):
    out = tr.delete_theme(tr.DeleteRequest(id="theme-9"))
    assert out == {"ok": True}
    assert fake_storage["deleted_id"] == "theme-9"


def test_get_theme_hit(fake_storage):
    out = tr.get_theme("theme-1")
    assert out["id"] == "theme-1"


def test_get_theme_miss_404(fake_storage):
    with pytest.raises(HTTPException) as ei:
        tr.get_theme("ghost")
    assert ei.value.status_code == 404


def test_payload_rejects_name_over_32_chars():
    with pytest.raises(ValidationError):
        _payload(name="x" * 33)


def test_payload_rejects_name_empty():
    with pytest.raises(ValidationError):
        _payload(name="")


def test_payload_rejects_bad_appearance():
    with pytest.raises(ValidationError):
        _payload(appearance="blue")


def test_payload_rejects_empty_css():
    with pytest.raises(ValidationError):
        _payload(css="")


def test_payload_rejects_css_over_8192():
    with pytest.raises(ValidationError):
        _payload(css="a" * 8193)


def test_payload_accepts_minimal_valid():
    payload = _payload(cover=None)
    assert payload.appearance == "light"
    assert payload.cover is None
