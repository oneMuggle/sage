# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""站点登录态探针：根据渲染后的页面特征判断"已登录 / 需要登录 / 无法确认"。

只做启发式判断，不保证 100% 准确；无法确认时如实返回 ``unknown``，
不把公开页面的"登录"入口误报为过期，也不把模糊页面冒充已登录。
"""

from __future__ import annotations

from typing import Any, Dict

#: 明确“已登录”的页面标记（中英文常见文案）
_LOGGED_IN_MARKERS = (
    "退出登录",
    "退出帳號",
    "注销",
    "个人中心",
    "我的账户",
    "我的帐号",
    "log out",
    "logout",
    "sign out",
)

#: 明确“未登录 / 需要登录”的页面标记
_LOGIN_MARKERS = (
    "请登录",
    "登录后",
    "立即登录",
    "sign in",
    "log in",
    "login",
)

#: 只看正文前 N 字符，避免超长页面拖慢判断
_TEXT_CAP = 20_000


def classify_session_page(rendered: Dict[str, Any]) -> str:
    """把 ``render_page`` 结果分类为 ``logged_in`` / ``login_required`` / ``unknown``。"""
    if not isinstance(rendered, dict):
        return "unknown"
    if rendered.get("login_wall"):
        return "login_required"
    status = rendered.get("rendered_status")
    if isinstance(status, int) and status >= 400:
        return "unknown"
    text = str(rendered.get("content") or "")[:_TEXT_CAP]
    lowered = text.lower()
    logged_in_markers = (marker.lower() for marker in _LOGGED_IN_MARKERS)
    if any(marker in lowered for marker in logged_in_markers):
        return "logged_in"
    login_markers = (marker.lower() for marker in _LOGIN_MARKERS)
    if any(marker in lowered for marker in login_markers):
        return "login_required"
    return "unknown"


__all__ = ["classify_session_page"]
