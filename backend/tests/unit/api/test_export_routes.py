"""R123 — 会话导出路由单元测试。

handler 直调（不起 HTTP server），monkeypatch session_export 服务函数。
覆盖：JSON 信封形态、主题归一化、markdown 分派、Accept 双形态（HTML
直返 attachment vs JSON 信封）、404 映射、body 缺省、extra=forbid、
format 回落。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api import export_routes as er
from backend.api.export_routes import ExportSessionRequest, export_session
from backend.application.services.session_export import SessionNotFoundError

pytestmark = pytest.mark.unit


def _result(session_id="s1"):
    return SimpleNamespace(
        html="<html>hi</html>",
        filename="session-s1.html",
        session_id=session_id,
        message_count=3,
        theme="dark",
    )


@pytest.fixture()
def fake_html(monkeypatch):
    calls = {}

    def fake_export(session_id, theme="auto"):
        calls["args"] = (session_id, theme)
        return _result(session_id)

    monkeypatch.setattr(er, "export_session_to_html", fake_export)
    return calls


def test_default_json_envelope(fake_html):
    out = export_session("s1", accept=None)
    assert out["html"] == "<html>hi</html>"
    assert out["filename"] == "session-s1.html"
    assert out["session_id"] == "s1"
    assert out["message_count"] == 3
    assert out["theme"] == "dark"


def test_invalid_theme_normalized_to_auto(fake_html):
    export_session("s1", ExportSessionRequest(theme="neon"), accept=None)
    assert fake_html["args"] == ("s1", "auto")  # 非法主题归一化后透传


def test_markdown_format_dispatch(fake_html, monkeypatch):
    calls = {}

    def fake_md(session_id):
        calls["session_id"] = session_id
        return SimpleNamespace(
            html="# md",
            filename="s1.md",
            session_id=session_id,
            message_count=1,
            theme="auto",
        )

    monkeypatch.setattr(er, "export_session_to_markdown", fake_md)
    out = export_session("s1", ExportSessionRequest(format="markdown"), accept=None)
    assert calls["session_id"] == "s1"
    assert out["theme"] == "auto"  # markdown 不适用主题，恒回 DEFAULT_THEME


def test_invalid_format_falls_back_to_html(fake_html, monkeypatch):
    md_called = []
    monkeypatch.setattr(
        er,
        "export_session_to_markdown",
        lambda sid: md_called.append(sid) or _result(sid),
    )
    export_session("s1", ExportSessionRequest(format="pdf"), accept=None)
    assert md_called == []  # 非 markdown 值回落 html 导出


def test_accept_html_returns_attachment(fake_html):
    resp = export_session("s1", accept="text/html")
    assert resp.body == b"<html>hi</html>"
    assert resp.status_code == 200
    assert resp.headers["content-disposition"] == (
        'attachment; filename="session-s1.html"'
    )


def test_accept_html_with_json_stays_envelope(fake_html):
    out = export_session("s1", accept="text/html, application/json")
    assert out["html"] == "<html>hi</html>"  # JSON 优先，不返回 attachment


def test_session_not_found_maps_to_404(monkeypatch):
    def boom(session_id, theme="auto"):
        raise SessionNotFoundError("nope")

    monkeypatch.setattr(er, "export_session_to_html", boom)
    with pytest.raises(HTTPException) as excinfo:
        export_session("ghost", accept=None)
    assert excinfo.value.status_code == 404


def test_body_none_uses_defaults(fake_html):
    export_session("s1", None, accept=None)
    assert fake_html["args"] == ("s1", "auto")  # 缺省 auto 主题


def test_request_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        ExportSessionRequest.model_validate({"theme": "auto", "bogus": 1})
