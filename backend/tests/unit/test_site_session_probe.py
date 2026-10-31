"""站点登录态探针分类测试。"""

from __future__ import annotations

import pytest

from backend.services.site_session_probe import classify_session_page

pytestmark = pytest.mark.unit


def test_login_wall_marks_login_required():
    assert classify_session_page({"login_wall": True, "content": "任意"}) == "login_required"


def test_logged_in_markers():
    rendered = {"content": "欢迎回来，张三 退出登录 个人中心"}
    assert classify_session_page(rendered) == "logged_in"


def test_login_markers():
    rendered = {"content": "请登录后查看全文"}
    assert classify_session_page(rendered) == "login_required"


def test_ambiguous_page_is_unknown():
    assert classify_session_page({"content": "普通公开页面"}) == "unknown"


def test_http_error_is_unknown():
    assert classify_session_page({"content": "退出登录", "rendered_status": 503}) == "unknown"
